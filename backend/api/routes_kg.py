"""
KG API routes: ingest, query, pending review, conflicts, evolution.
"""
import hashlib
import json
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from modules.knowledge_graph.schema import schema_manager
from modules.knowledge_graph.kg_store import kg_store
from modules.knowledge_graph import source_store, evolution_tracker, conflict_checker
from modules.knowledge_graph.reference_lookup import reference_lookup
from modules.knowledge_graph.extractor import extract_from_text, EntityProposal, RelationProposal

import threading

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])

NEWS_CACHE = pathlib.Path(__file__).parents[2] / "data" / "news" / "cache.json"
PENDING_FILE = pathlib.Path(__file__).parents[2] / "data" / "kg" / "pending.json"
PROPOSED_TYPES_FILE = pathlib.Path(__file__).parents[2] / "data" / "kg" / "proposed_types.json"

# ── In-memory caches (loaded once, written in background threads) ─────────────

_pending_cache: dict | None = None
_pending_lock = threading.Lock()

_proposed_types_cache: dict | None = None
_proposed_types_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_country(country: str) -> str:
    """Normalize country name variants to canonical form."""
    if not country:
        return country
    normalized_map = {
        "usa": "USA",
        "u.s.a": "USA",
        "u.s.a.": "USA",
        "united states": "USA",
        "united states of america": "USA",
        "the united states": "USA",
        "ussr": "Russia",
        "soviet union": "Russia",
        "u.k.": "United Kingdom",
        "united kingdom": "United Kingdom",
        "p.r. china": "China",
        "peoples republic of china": "China",
        "prc": "China",
    }
    key = country.strip().lower()
    return normalized_map.get(key, country.strip())


def _load_pending() -> dict:
    global _pending_cache
    if _pending_cache is not None:
        return _pending_cache
    if not PENDING_FILE.exists():
        _pending_cache = {"pending": []}
    else:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            _pending_cache = json.load(f)
    return _pending_cache


def _save_pending(data: dict) -> None:
    global _pending_cache
    _pending_cache = data
    def _write():
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _pending_lock:
            with open(PENDING_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    threading.Thread(target=_write, daemon=True).start()


def _load_proposed_types() -> dict:
    global _proposed_types_cache
    if _proposed_types_cache is not None:
        return _proposed_types_cache
    if not PROPOSED_TYPES_FILE.exists():
        _proposed_types_cache = {}
    else:
        with open(PROPOSED_TYPES_FILE, "r", encoding="utf-8") as f:
            _proposed_types_cache = json.load(f)
    return _proposed_types_cache


def _save_proposed_types(data: dict) -> None:
    global _proposed_types_cache
    _proposed_types_cache = data
    def _write():
        PROPOSED_TYPES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _proposed_types_lock:
            with open(PROPOSED_TYPES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    threading.Thread(target=_write, daemon=True).start()


def _source_id_from_url(url: str) -> str:
    return "sha_" + hashlib.sha256(url.encode()).hexdigest()[:16]


def _source_id_from_text(text: str) -> str:
    return "sha_" + hashlib.sha256(text.encode()).hexdigest()[:16]


def _attrs_to_dict(attrs: dict) -> dict:
    """Convert AttributeValue objects to JSON-serializable dict."""
    return {
        k: {"value": v.value, "event_date": v.event_date, "source_id": v.source_id}
        for k, v in attrs.items()
    }


# ── Maneuver enrichment helpers ───────────────────────────────────────────────

def _classify_maneuver_type(ev: dict) -> str:
    """Classify maneuver into coarse categories based on extracted fields."""
    incl = ev.get("jco_incl_change") or ev.get("inclination_change") or 0
    period = ev.get("jco_period_change") or ev.get("period_change") or 0
    dv = ev.get("jco_delta_v") or ev.get("delta_v") or 0
    if abs(float(incl)) > 0.05:
        return "plane change"
    if abs(float(period)) > 0.5:
        return "altitude change"
    if float(dv) > 0 or abs(float(period)) > 0:
        return "stationkeeping"
    return "unknown"


def _estimate_dv_from_period_change(pre_period_min: float, post_period_min: float) -> float:
    """Rough Vis-viva estimate of delta-V (m/s) from orbital period change.

    Assumes near-circular low Earth orbit (r ≈ 6778 km baseline for ~90 min period).
    ΔV ≈ v * |Δa| / (3a) where a = semi-major axis, v = circular velocity.
    For practical SSA purposes this approximation is sufficient.
    """
    import math
    MU = 398600.4418  # km^3/s^2
    # Convert period to semi-major axis via Kepler's third law: a^3 = μ(T/2π)^2
    def period_to_sma(t_min: float) -> float:
        t_s = t_min * 60.0
        return (MU * (t_s / (2 * math.pi)) ** 2) ** (1 / 3)

    a_pre = period_to_sma(pre_period_min)
    a_post = period_to_sma(post_period_min)
    a_avg = (a_pre + a_post) / 2
    v_avg = math.sqrt(MU / a_avg) * 1000  # m/s
    delta_a = abs(a_post - a_pre)
    return round(v_avg * delta_a / (2 * a_avg), 3)


async def _enrich_maneuver_event(ev: dict, kg_store_ref) -> None:
    """Enrich a maneuver event with TLE-derived orbital change data in-place."""
    from modules.propagation.tle_history import get_closest_before
    from modules.events.event_store import classify_regime

    event_dt_str = ev.get("event_date", "")
    if not event_dt_str:
        return
    try:
        from datetime import datetime, timezone, timedelta
        event_dt = datetime.fromisoformat(event_dt_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return

    # Rename JCO-extracted fields to jco_* prefix (keep originals as aliases)
    for field in ("delta_v", "period_change", "inclination_change", "apogee_change", "perigee_change"):
        if field in ev and f"jco_{field}" not in ev:
            ev[f"jco_{field}"] = ev[field]

    sat_id = ev.get("satellite_id", "")

    # TLE just before maneuver
    tle_pre = get_closest_before(sat_id, event_dt - timedelta(hours=1)) if sat_id else None
    # TLE just after maneuver (24h later to allow Space-Track update lag)
    tle_post = get_closest_before(sat_id, event_dt + timedelta(hours=25)) if sat_id else None

    ev["tle_available"] = False
    if tle_pre and tle_post:
        # Only process if TLE actually changed (i.e., post-maneuver TLE is available and different)
        if tle_pre.get("line2") != tle_post.get("line2"):
            try:
                pre_period = 1440.0 / float(tle_pre["line2"][52:63])
                post_period = 1440.0 / float(tle_post["line2"][52:63])
                ev["tle_pre_period"] = round(pre_period, 4)
                ev["tle_post_period"] = round(post_period, 4)
                ev["tle_period_change"] = round(post_period - pre_period, 4)
                ev["tle_incl_change"] = round(
                    float(tle_post["line2"][8:16]) - float(tle_pre["line2"][8:16]), 4
                )
                ev["tle_delta_v_est"] = _estimate_dv_from_period_change(pre_period, post_period)
                ev["tle_available"] = True

                # Only calculate discrepancy if both JCO and TLE values are meaningful
                jco_dv = ev.get("jco_delta_v") or ev.get("delta_v") or 0
                tle_dv = ev["tle_delta_v_est"]
                if float(jco_dv) > 0 and tle_dv > 0:
                    pct = abs(float(jco_dv) - tle_dv) / max(float(jco_dv), tle_dv)
                    ev["discrepancy_pct"] = round(pct, 3)
                    ev["discrepancy_flag"] = pct > 0.25
            except (ValueError, IndexError):
                pass
        else:
            # TLE pre and post exist but are identical (no post-maneuver TLE update yet)
            # Don't show discrepancy flag — no basis for comparison
            ev["tle_available"] = False

    ev["maneuver_type"] = _classify_maneuver_type(ev)

    # Orbital regime from KG node
    node = kg_store_ref.nodes.get(sat_id)
    period_attr = ((node.get("attributes") or {}).get("orbital_period") or {}).get("value") if node else None
    if period_attr is not None:
        try:
            ev["regime"] = classify_regime(float(period_attr))
        except (TypeError, ValueError):
            pass


# ── Ingest pipeline ───────────────────────────────────────────────────────────

async def _run_ingest(
    text: str,
    source: dict,
    source_id: str,
    mode: str,
    force: bool = False,
) -> dict:
    """Core ingest logic. Returns summary dict."""
    # Deduplication
    if not force and kg_store.is_processed(source_id):
        return {"status": "already_ingested", "source_id": source_id, "message": "Document already processed. No LLM calls made."}

    # Save source
    source_store.save_source(source_id, {
        "type": source.get("type", "unknown"),
        "title": source.get("title", ""),
        "url": source.get("url", ""),
        "date": source.get("date") or source.get("published_at", ""),
        "news_site": source.get("news_site", ""),
        "related_norad_ids": source.get("related_norad_ids") or [],
    }, {"source_id": source_id, "text": text[:50000], **source})

    kg_store.register_source(source_id, {
        "type": source.get("type", "unknown"),
        "title": source.get("title", ""),
        "url": source.get("url", ""),
        "date": source.get("date") or source.get("published_at", ""),
        "news_site": source.get("news_site", ""),
    })

    # Mark as processed BEFORE LLM call to prevent races
    kg_store.mark_processed(source_id)
    kg_store.save()

    # LLM extraction
    result = await extract_from_text(text, {**source, "source_id": source_id}, schema_manager, kg_store)

    pending_data = _load_pending()
    proposals = []
    proposed_types = _load_proposed_types()

    source_ref = {
        "source_id": source_id,
        "date": source.get("date") or source.get("published_at", ""),
    }
    event_date = result.event_date or source.get("date") or source.get("published_at", "")

    # Types that represent the source document itself — stored as metadata, not KG nodes
    _DOCUMENT_TYPES = {"NewsArticle", "JCOReport", "Document"}
    # Relationships that link documents to entities — stored as provenance, not KG edges
    _PROVENANCE_PREDICATES = {"mentions", "references", "cites"}

    # ── Process entities ──
    label_to_id: dict[str, str] = {}  # track IDs assigned in this extraction run

    for ep in result.entities:
        # Skip document nodes — the source article is already stored as provenance metadata
        if ep.type in _DOCUMENT_TYPES or (ep.inferred_types and any(t in _DOCUMENT_TYPES for t in ep.inferred_types)):
            label_to_id[ep.label] = source_id  # map label → source_id so relations referencing it are also dropped
            continue
        # Entity linking
        existing = None
        if ep.id:
            candidate = kg_store.nodes.get(ep.id)
            if candidate:
                # Validate: reject if labels don't substantially overlap (prevents e.g. FORMOSAT-7 → FORMOSAT-5)
                from modules.knowledge_graph.kg_store import _normalize_label
                ep_lbl = ep.label.lower()
                cand_lbl = candidate.get("label", "").lower()
                if (ep_lbl == cand_lbl or ep_lbl in cand_lbl or cand_lbl in ep_lbl
                        or _normalize_label(ep.label) == _normalize_label(cand_lbl)):
                    existing = candidate
                # else: LLM linked to a different entity — treat as new
        if not existing and ep.label:
            existing = kg_store.find_node_by_label(ep.label)

        # For satellites, prefer norad_id as the canonical node ID so it matches EarthView lookups
        # Use exact type check — "Satellite" in ep.type is a substring match that would wrongly
        # catch SatelliteConstellation / SatelliteSeries
        _is_satellite = ep.type == "Satellite" or "Satellite" in (ep.inferred_types or [])
        norad_id_val = None
        if _is_satellite:
            norad_attr = ep.attributes.get("norad_id")
            if norad_attr and getattr(norad_attr, "value", None):
                norad_id_val = str(norad_attr.value).strip()

        node_id = (existing["id"] if existing else None) or norad_id_val or ep.id or ep.label.lower().replace(" ", "_").replace("-", "_")
        label_to_id[ep.label] = node_id

        # Enrich satellite attributes from reference CSV (fills only null/missing fields)
        is_satellite = _is_satellite
        if is_satellite:
            attrs_dict_raw = {k: v.__dict__ if hasattr(v, '__dict__') else v
                              for k, v in ep.attributes.items()}
            fills = reference_lookup.enrich(ep.label, _attrs_to_dict(ep.attributes),
                                            norad_id=str(norad_id_val or ""))
            for attr_key, val in fills.items():
                existing_attr = ep.attributes.get(attr_key)
                cur_val = existing_attr.value if existing_attr and hasattr(existing_attr, 'value') else None
                if cur_val is None:
                    # Inject the filled value back into ep.attributes structure
                    from modules.knowledge_graph.extractor import AttributeValue
                    ep.attributes[attr_key] = AttributeValue(
                        value=val, event_date=event_date, source_id="reference_csv"
                    )
            # Also update node_id if reference gives us a NORAD ID we didn't have
            if not norad_id_val and fills.get("norad_id"):
                norad_id_val = str(fills["norad_id"])
                node_id = norad_id_val
                label_to_id[ep.label] = node_id

        # Handle proposed new types
        if ep.schema_status == "proposed" and ep.proposed_type_info:
            type_name = ep.type
            if type_name not in proposed_types:
                proposed_types[type_name] = {
                    "proposed_type": type_name,
                    "suggested_parent": ep.proposed_type_info.get("suggested_parent", "Entity"),
                    "suggested_attributes": ep.proposed_type_info.get("suggested_attributes", []),
                    "reason": ep.proposed_type_info.get("reason", ""),
                    "first_seen_source": source_id,
                    "first_seen_date": event_date,
                    "node_count": 0,
                    "schema_status": "proposed",
                }
            proposed_types[type_name]["node_count"] = proposed_types[type_name].get("node_count", 0) + 1

        attrs_dict = _attrs_to_dict(ep.attributes)
        # Strip attributes not declared in the schema for this type (prevents hallucinated fields)
        if ep.schema_status != "proposed":
            valid_attrs = set(schema_manager.get_resolved_attributes(ep.type).keys())
            stripped = [k for k in attrs_dict if k not in valid_attrs]
            if stripped:
                print(f"[ingest] stripped undeclared attributes from {ep.label} ({ep.type}): {stripped}")
            attrs_dict = {k: v for k, v in attrs_dict.items() if k in valid_attrs}
        node_data = {
            "id": node_id,
            "label": ep.label,
            "type": ep.type,
            "inferred_types": ep.inferred_types,
            "schema_status": ep.schema_status,
            "attributes": attrs_dict,
            "sources": [source_ref],
        }

        if existing:
            # Check for attribute conflicts on existing nodes
            for attr_key, new_attr in attrs_dict.items():
                old_attr = existing.get("attributes", {}).get(attr_key)
                if old_attr and old_attr.get("value") is not None and new_attr.get("value") is not None:
                    if str(old_attr["value"]) != str(new_attr["value"]):
                        field_meta = schema_manager.get_resolved_attributes(ep.type).get(attr_key, {})
                        result_type, reasoning = await conflict_checker.assess_attribute_conflict(
                            node_id, attr_key, field_meta,
                            old_attr["value"], old_attr.get("event_date"),
                            kg_store.sources.get(old_attr.get("source_id", ""), {}).get("title", "unknown"),
                            new_attr["value"], new_attr.get("event_date"),
                            source.get("title", "unknown"),
                        )
                        if result_type == "duplicate":
                            pass  # keep existing
                        elif result_type == "update":
                            pending_item = {
                                "id": f"p_{uuid.uuid4().hex[:8]}",
                                "type": "attribute_update",
                                "status": "pending",
                                "source_id": source_id,
                                "entity_id": node_id,
                                "field": attr_key,
                                "old_value": old_attr["value"],
                                "new_value": new_attr["value"],
                                "llm_assessment": reasoning,
                                "evidence": {"excerpt": ep.excerpt, "source": source},
                                "created_at": _now(),
                            }
                            proposals.append(pending_item)
                            if mode == "auto":
                                existing.get("attributes", {})[attr_key] = new_attr
                                evolution_tracker.log({"event_date": event_date, "change_type": "attribute_changed",
                                    "entity_id": node_id, "field": attr_key,
                                    "old_value": old_attr["value"], "new_value": new_attr["value"],
                                    "source_id": source_id})
                        else:  # contradiction
                            conflict_item = {
                                "id": f"p_{uuid.uuid4().hex[:8]}",
                                "type": "conflict",
                                "status": "pending",
                                "source_id": source_id,
                                "conflict": {
                                    "field": attr_key, "entity_id": node_id,
                                    "option_a": {"value": old_attr["value"], "source": kg_store.sources.get(old_attr.get("source_id", ""), {}), "excerpt": ""},
                                    "option_b": {"value": new_attr["value"], "source": source, "excerpt": ep.excerpt},
                                    "llm_assessment": reasoning,
                                },
                                "created_at": _now(),
                            }
                            proposals.append(conflict_item)
                            kg_store.add_conflict({"id": conflict_item["id"], "entity_id": node_id,
                                "field": attr_key, "assessment": reasoning, "detected_at": _now()})
            # Merge source ref
            if mode == "auto":
                kg_store.upsert_node(node_data)
                evolution_tracker.log({"event_date": event_date, "change_type": "source_added",
                    "entity_id": node_id, "source_id": source_id})
        else:
            # New entity
            pending_item = {
                "id": f"p_{uuid.uuid4().hex[:8]}",
                "type": "node_add",
                "status": "pending",
                "source_id": source_id,
                "proposed": node_data,
                "evidence": {"excerpt": ep.excerpt, "source": source},
                "created_at": _now(),
            }
            proposals.append(pending_item)
            if mode == "auto":
                kg_store.upsert_node(node_data)
                evolution_tracker.log({"event_date": event_date, "change_type": "node_added",
                    "entity_id": node_id, "source_id": source_id})

    # ── Process relations ──
    for rp in result.relations:
        # Skip provenance-style predicates — source info lives on node/edge metadata
        if rp.predicate in _PROVENANCE_PREDICATES:
            continue
        subject_id = label_to_id.get(rp.subject_label) or (kg_store.find_node_by_label(rp.subject_label) or {}).get("id")
        object_id = label_to_id.get(rp.object_label) or (kg_store.find_node_by_label(rp.object_label) or {}).get("id")
        if not subject_id or not object_id:
            continue
        # Drop any relation where either endpoint is a document/source node
        if subject_id == source_id or object_id == source_id:
            continue

        # Validate edge direction against schema domain/range constraints.
        # Nodes proposed in the same extraction run may not be in kg_store yet — look them
        # up from pending proposals first so newly-proposed satellites don't get their edges dropped.
        schema_warning: str | None = None
        rel_meta = schema_manager.get_relationship_types().get(rp.predicate)
        if rel_meta:
            def _node_types(node_id: str) -> set[str]:
                """Return type set for a node, checking kg_store then pending proposals."""
                node = kg_store.nodes.get(node_id)
                if node:
                    return set([node.get("type", "")] + (node.get("inferred_types") or [])) - {""}
                # Fall back: scan pending proposals created in this run
                for item in pending_data.get("pending", []):
                    if item.get("type") == "node_add":
                        p = item.get("proposed") or {}
                        if p.get("id") == node_id:
                            t = p.get("type", "")
                            return set([t] + (p.get("inferred_types") or [])) - {""}
                return set()  # unknown

            s_types = _node_types(subject_id)
            o_types = _node_types(object_id)
            domain = set(rel_meta.get("domain", []))
            range_ = set(rel_meta.get("range", []))

            s_known = bool(s_types)
            o_known = bool(o_types)

            if s_known and o_known:
                # Both types known — full validation
                forward_ok = bool(s_types & domain) and bool(o_types & range_)
                reverse_ok = bool(o_types & domain) and bool(s_types & range_)
                if not forward_ok and reverse_ok:
                    subject_id, object_id = object_id, subject_id
                    print(f"[routes_kg] auto-flipped {rp.predicate}: '{rp.subject_label}' ↔ '{rp.object_label}'")
                elif not forward_ok and not reverse_ok:
                    print(f"[routes_kg] skipped invalid edge: '{rp.subject_label}' --[{rp.predicate}]→ '{rp.object_label}' (types {s_types} / {o_types} don't match domain={domain} range={range_})")
                    continue
            elif s_known and not o_known:
                # Only subject type known
                if s_types & range_ and not (s_types & domain):
                    subject_id, object_id = object_id, subject_id  # subject looks like range → flip
                elif not (s_types & domain) and not (s_types & range_):
                    schema_warning = f"Subject '{rp.subject_label}' (type {s_types}) not in domain {domain} or range {range_} for '{rp.predicate}'"
            elif o_known and not s_known:
                # Only object type known
                if o_types & domain and not (o_types & range_):
                    subject_id, object_id = object_id, subject_id  # object looks like domain → flip
                elif not (o_types & domain) and not (o_types & range_):
                    schema_warning = f"Object '{rp.object_label}' (type {o_types}) not in domain {domain} or range {range_} for '{rp.predicate}'"
            # If neither type is known, allow through for human review

        new_edge = {
            "source": subject_id,
            "label": rp.predicate,
            "target": object_id,
            "sources": [source_ref],
        }
        existing_edges = kg_store.find_edges_by_source_label(subject_id, rp.predicate)

        if not existing_edges:
            pending_item = {
                "id": f"p_{uuid.uuid4().hex[:8]}",
                "type": "edge_add",
                "status": "pending",
                "source_id": source_id,
                "proposed": new_edge,
                "evidence": {"excerpt": rp.excerpt, "source": source},
                "created_at": _now(),
            }
            if schema_warning:
                pending_item["llm_assessment"] = f"⚠ Schema warning: {schema_warning}"
            proposals.append(pending_item)
            if mode == "auto":
                kg_store.upsert_edge(new_edge)
                evolution_tracker.log({"event_date": event_date, "change_type": "edge_added",
                    "edge_id": kg_store._edge_id(subject_id, rp.predicate, object_id),
                    "source_id": source_id})
        else:
            for ex_edge in existing_edges:
                if ex_edge["target"] == object_id:
                    if not conflict_checker.is_exact_duplicate(new_edge, ex_edge):
                        # Add source ref to existing edge
                        if mode == "auto":
                            kg_store.upsert_edge({**new_edge, "id": ex_edge["id"]})
                    break
            else:
                # Same subject+predicate, different object → assess conflict
                ex_edge = existing_edges[0]
                conflict_result, reasoning = await conflict_checker.assess_conflict(
                    new_edge, ex_edge, schema_manager,
                    source_a_meta=kg_store.sources.get(
                        (ex_edge.get("sources") or [{}])[0].get("source_id", ""), {}),
                    source_b_meta=source,
                )
                if conflict_result == "compatible":
                    pending_item = {
                        "id": f"p_{uuid.uuid4().hex[:8]}",
                        "type": "edge_add",
                        "status": "pending",
                        "source_id": source_id,
                        "proposed": new_edge,
                        "evidence": {"excerpt": rp.excerpt, "source": source},
                        "created_at": _now(),
                    }
                    proposals.append(pending_item)
                    if mode == "auto":
                        kg_store.upsert_edge(new_edge)
                elif conflict_result == "contradiction":
                    conflict_item = {
                        "id": f"p_{uuid.uuid4().hex[:8]}",
                        "type": "conflict",
                        "status": "pending",
                        "source_id": source_id,
                        "conflict": {
                            "option_a": {"edge": ex_edge, "source": kg_store.sources.get(
                                (ex_edge.get("sources") or [{}])[0].get("source_id", ""), {})},
                            "option_b": {"edge": new_edge, "source": source, "excerpt": rp.excerpt},
                            "llm_assessment": reasoning,
                        },
                        "created_at": _now(),
                    }
                    proposals.append(conflict_item)
                    kg_store.add_conflict({"id": conflict_item["id"],
                        "edge_a": ex_edge.get("id"), "edge_b": "pending",
                        "assessment": reasoning, "detected_at": _now()})

    # Save pending proposals
    pending_data["pending"].extend(proposals)
    _save_pending(pending_data)
    _save_proposed_types(proposed_types)

    if mode == "auto":
        kg_store.save()

    # Auto-extract satellite events if text looks like a JCO/MMB report
    events_extracted = 0
    _jco_keywords = {"maneuver", "delta_v", "period change", "photometric", "mission management board"}
    if sum(1 for kw in _jco_keywords if kw in text.lower()) >= 2:
        try:
            from modules.events.jco_extractor import extract_events_from_jco
            from modules.events.event_store import event_store as _event_store
            events = await extract_events_from_jco(text, {**source, "source_id": source_id})
            for ev in events:
                ev["source_id"] = source_id
                ev.setdefault("report_title", source.get("title", ""))
                if ev.get("type") == "maneuver":
                    await _enrich_maneuver_event(ev, kg_store)
                _event_store.add_event(ev)
            events_extracted = len(events)
            print(f"[events] extracted {events_extracted} events from {source_id}")
        except Exception as _e:
            print(f"[events] extraction failed: {_e}")

    # Auto-extract launch events if text looks like a NOTOS/NOTAM document
    import re as _re
    _notam_keywords = {"notamn", "qrdca", "sfc-unl"}
    if sum(1 for kw in _notam_keywords if kw in text.lower()) >= 2:
        try:
            from modules.events.notam_extractor import extract_launch_events
            from modules.events.event_store import event_store as _event_store
            from api.routes_propagation import _fetch_and_cache_tle

            launches = await extract_launch_events(text, {**source, "source_id": source_id})
            for ev in launches:
                ev["source_id"] = source_id
                ev.setdefault("report_title", source.get("title", ""))

                sat_label = ev.get("satellite_label") or ""
                sat_norad = ev.get("satellite_id") or ""   # real NORAD only (null for NOTOS-only)
                sat_notos = ev.get("notos_id") or ""       # NOTOS provisional number

                # Look for an already-committed KG node
                existing = (kg_store.find_node_by_label(sat_label) if sat_label else None) \
                        or (kg_store.nodes.get(sat_norad) if sat_norad else None)

                if existing:
                    ev["satellite_id"] = existing["id"]
                elif sat_norad and sat_norad.isdigit():
                    # Confirmed NORAD ID but node not yet in KG (may be in pending queue).
                    # Use the NORAD ID directly so the event lands on the right node once approved.
                    ev["satellite_id"] = sat_norad
                    attrs: dict = {
                        "norad_id": {"value": sat_norad, "event_date": None, "source_id": source_id},
                    }
                    if sat_notos:
                        attrs["notos_id"] = {"value": sat_notos, "event_date": None, "source_id": source_id}
                    if ev.get("orbital_inclination") is not None:
                        attrs["inclination"] = {"value": ev["orbital_inclination"], "event_date": ev.get("event_date"), "source_id": source_id}
                    if ev.get("orbital_period") is not None:
                        attrs["orbital_period"] = {"value": ev["orbital_period"], "event_date": ev.get("event_date"), "source_id": source_id}
                    new_node = {
                        "id": sat_norad, "label": sat_label or sat_norad, "type": "Satellite",
                        "inferred_types": schema_manager.get_ancestors("Satellite"),
                        "schema_status": "confirmed",
                        "attributes": attrs,
                        "sources": [{"source_id": source_id, "date": source.get("date", "")}],
                    }
                    kg_store.upsert_node(new_node)
                    kg_store.save()
                    _fetch_and_cache_tle(sat_norad)
                elif sat_label:
                    # No NORAD confirmed — use label slug
                    slug = _re.sub(r"[^a-z0-9]+", "_", sat_label.lower()).strip("_")
                    attrs = {}
                    if sat_notos:
                        attrs["notos_id"] = {"value": sat_notos, "event_date": None, "source_id": source_id}
                    if ev.get("orbital_inclination") is not None:
                        attrs["inclination"] = {"value": ev["orbital_inclination"], "event_date": ev.get("event_date"), "source_id": source_id}
                    if ev.get("orbital_period") is not None:
                        attrs["orbital_period"] = {"value": ev["orbital_period"], "event_date": ev.get("event_date"), "source_id": source_id}
                    new_node = {
                        "id": slug, "label": sat_label, "type": "Satellite",
                        "inferred_types": schema_manager.get_ancestors("Satellite"),
                        "schema_status": "confirmed",
                        "attributes": attrs,
                        "sources": [{"source_id": source_id, "date": source.get("date", "")}],
                    }
                    kg_store.upsert_node(new_node)
                    kg_store.save()
                    ev["satellite_id"] = slug

                _event_store.add_event(ev)

            events_extracted += len(launches)
            if launches:
                print(f"[events] extracted {len(launches)} launch events from {source_id}")
        except Exception as _e:
            print(f"[events] NOTAM extraction failed: {_e}")

    return {
        "status": "review_required" if mode == "review" else "auto_applied",
        "source_id": source_id,
        "proposed": len(proposals),
        "events_extracted": events_extracted,
        "mode": mode,
        "truncated": result.truncated,
        "original_length": result.original_length,
    }


# ── Ingest endpoints ──────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    text: str
    mode: Literal["review", "auto"] = "review"
    source: dict = {}


@router.post("/ingest")
async def ingest(req: IngestRequest):
    url = req.source.get("url", "")
    source_id = f"snapi_{req.source['id']}" if "id" in req.source else (
        _source_id_from_url(url) if url else _source_id_from_text(req.text)
    )
    return await _run_ingest(req.text, req.source, source_id, req.mode)


def _extract_mhtml_text(raw_bytes: bytes) -> str:
    """Extract readable text from an .mhtml / .mht web archive file."""
    import email
    from bs4 import BeautifulSoup

    # Parse as MIME message
    msg = email.message_from_bytes(raw_bytes)
    html = ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                try:
                    decoded = payload.decode(charset, errors="replace")
                except Exception:
                    decoded = payload.decode("utf-8", errors="replace")
                if ct == "text/html":
                    html = decoded
                    break  # prefer HTML over plain text
                elif not html:
                    html = decoded

    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    parts = []
    title_tag = soup.find("title")
    if title_tag:
        parts.append(title_tag.get_text(strip=True))
    body = soup.find("body") or soup
    for tag in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "pre", "blockquote"]):
        t = tag.get_text(separator=" ", strip=True)
        if len(t) > 20:
            parts.append(t)
    return "\n\n".join(parts)[:40000]


@router.post("/ingest/pdf")
async def ingest_pdf(
    file: UploadFile = File(...),
    title: str = Form(""),
    date: str = Form(""),
    source_type: str = Form("report"),
    mode: str = Form("review"),
):
    file_bytes = await file.read()
    fname = (file.filename or "").lower()
    source_id = "file_" + hashlib.sha256(file_bytes).hexdigest()[:16]
    warnings: list[str] = []

    if fname.endswith(".mhtml") or fname.endswith(".mht"):
        text = _extract_mhtml_text(file_bytes)
        if not text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from .mhtml file")
        source = {
            "type": source_type,
            "title": title or file.filename,
            "date": date or "",
            "url": "",
        }
    else:
        from modules.knowledge_graph.pdf_parser import extract_text as pdf_extract
        result = pdf_extract(file_bytes)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        text = result["text"]
        meta = result["metadata"]
        source = {
            "type": source_type,
            "title": title or meta.get("title") or file.filename,
            "date": date or meta.get("creation_date", ""),
            "url": "",
        }
        if result["scanned_pages"]:
            warnings.append(f"Scanned/unreadable pages (skipped): {result['scanned_pages']}")
        if result["figure_count"]:
            warnings.append(f"{result['figure_count']} embedded figures detected (content not extractable)")

    ingest_result = await _run_ingest(text, source, source_id, mode)
    return {**ingest_result, "warnings": warnings}


@router.post("/ingest/bulk")
async def ingest_bulk(mode: str = "auto"):
    """Ingest all articles from news cache."""
    if not NEWS_CACHE.exists():
        raise HTTPException(status_code=404, detail="News cache not found. Run news refresh first.")
    with open(NEWS_CACHE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    results = []
    for art in articles:
        source_id = f"snapi_{art['id']}"
        text = f"{art.get('title', '')}\n\n{art.get('summary', '')}"
        source = {
            "id": art["id"],
            "type": "news",
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "date": art.get("published_at", ""),
            "news_site": art.get("news_site", ""),
        }
        result = await _run_ingest(text, source, source_id, mode)
        results.append(result)

    already = sum(1 for r in results if r.get("status") == "already_ingested")
    processed = len(results) - already
    return {"total": len(results), "newly_processed": processed, "already_ingested": already}


# ── KG query endpoints ────────────────────────────────────────────────────────

@router.get("/full")
def get_full_kg():
    """Returns nodes and edges formatted for the frontend KGView."""
    data = kg_store.get_all()

    def _enrich_sources(raw_sources: list) -> list:
        enriched = []
        for s in raw_sources:
            sid = s.get("source_id", "")
            meta = kg_store.sources.get(sid, {})
            enriched.append({
                "source_id": sid,
                "title": meta.get("title") or sid,
                "url": meta.get("url") or "",
                "date": s.get("date") or meta.get("date") or "",
                "excerpt": s.get("excerpt") or "",
            })
        return enriched

    nodes = []
    for node in data["nodes"].values():
        nodes.append({
            "id": node["id"],
            "label": node["label"],
            "type": node["type"],
            "inferred_types": node.get("inferred_types", []),
            "attributes": node.get("attributes", {}),
            "sources": _enrich_sources(node.get("sources", [])),
            "created_at": node.get("created_at"),
            "updated_at": node.get("updated_at"),
        })
    edges = []
    for edge in data["edges"].values():
        edges.append({
            "id": edge["id"],
            "source": edge["source"],
            "target": edge["target"],
            "label": edge["label"],
            "sources": _enrich_sources(edge.get("sources", [])),
            "created_at": edge.get("created_at"),
            "updated_at": edge.get("updated_at"),
        })
    return {"nodes": nodes, "edges": edges}


@router.get("/subgraph/{node_id}")
def get_subgraph(node_id: str, hops: int = 1):
    return kg_store.get_subgraph(node_id, hops=hops)


@router.get("/conflicts")
def get_conflicts():
    return {"conflicts": kg_store.conflicts}


# ── Evolution ─────────────────────────────────────────────────────────────────

@router.get("/evolution")
def get_evolution():
    return {"events": evolution_tracker.get_all_events()}


@router.get("/evolution/{entity_id}")
def get_entity_evolution(entity_id: str):
    return {
        "entity_id": entity_id,
        "events": evolution_tracker.get_entity_history(entity_id),
        "report": evolution_tracker.generate_report(entity_id),
    }


# ── Pending review ────────────────────────────────────────────────────────────

@router.get("/pending")
def get_pending(status: str = "pending", type: str = ""):
    data = _load_pending()
    items = [p for p in data["pending"] if p.get("status") == status]
    if type:
        items = [p for p in items if p.get("type") == type]
    return {"pending": items, "total": len(items)}


@router.post("/pending/{item_id}/approve")
def approve_pending(item_id: str):
    data = _load_pending()
    item = next((p for p in data["pending"] if p["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Pending item not found")
    if item["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Item is already {item['status']}")

    item_type = item["type"]
    event_date = (item.get("evidence", {}).get("source", {}).get("date") or
                  item.get("evidence", {}).get("source", {}).get("published_at", ""))
    source_id = (item.get("evidence", {}).get("source", {}).get("source_id") or
                 item.get("proposed", {}).get("sources", [{}])[0].get("source_id", "") if item.get("proposed") else "")

    if item_type == "node_add":
        kg_store.apply_node(item["proposed"])
        evolution_tracker.log({"event_date": event_date, "change_type": "node_added",
            "entity_id": item["proposed"]["id"], "source_id": source_id})
    elif item_type == "edge_add":
        kg_store.apply_edge(item["proposed"])
        evolution_tracker.log({"event_date": event_date, "change_type": "edge_added",
            "edge_id": item["proposed"].get("id", ""), "source_id": source_id})
    elif item_type == "attribute_update":
        node = kg_store.nodes.get(item["entity_id"])
        if node:
            if item["field"] == "type":
                # Special case: update node type and recompute inferred_types
                new_type = item["new_value"]
                node["type"] = new_type
                node["inferred_types"] = schema_manager.get_ancestors(new_type)
            else:
                node.setdefault("attributes", {})[item["field"]] = {"value": item["new_value"], "event_date": event_date, "source_id": source_id}
            node["updated_at"] = datetime.now(timezone.utc).isoformat()
        evolution_tracker.log({"event_date": event_date, "change_type": "attribute_changed",
            "entity_id": item["entity_id"], "field": item["field"],
            "old_value": item["old_value"], "new_value": item["new_value"], "source_id": source_id})

    item["status"] = "approved"
    _save_pending(data)
    kg_store.save()
    return {"status": "approved", "id": item_id}


@router.post("/pending/{item_id}/reject")
def reject_pending(item_id: str, reason: str = ""):
    data = _load_pending()
    item = next((p for p in data["pending"] if p["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Pending item not found")
    item["status"] = "rejected"
    if reason:
        item["reject_reason"] = reason
    _save_pending(data)
    return {"status": "rejected", "id": item_id}


class ResolveRequest(BaseModel):
    choice: Literal["option_a", "option_b", "keep_both"]
    reason: str = ""


@router.post("/pending/{item_id}/resolve")
def resolve_conflict(item_id: str, req: ResolveRequest):
    data = _load_pending()
    item = next((p for p in data["pending"] if p["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Pending item not found")
    if item["type"] not in ("conflict", "merge"):
        raise HTTPException(status_code=400, detail="Item is not a conflict or merge")

    # ── Merge resolution ────────────────────────────────────────────────────────
    if item["type"] == "merge":
        merge = item.get("merge", {})
        node_a = merge.get("node_a", {})   # existing KG node
        node_b = merge.get("node_b", {})   # proposed new node
        proposed_id = node_b.get("id", "")

        if req.choice == "option_a":
            # Use existing node (A) as canonical; absorb node_b attributes and sources
            canonical_id = node_a["id"]
            target = kg_store.nodes.get(canonical_id, dict(node_a))
            target.setdefault("attributes", {})
            for key, val in node_b.get("attributes", {}).items():
                if key not in target["attributes"] or target["attributes"][key].get("value") is None:
                    target["attributes"][key] = val
            existing_srcs = {s["source_id"] for s in target.get("sources", [])}
            for src in node_b.get("sources", []):
                if src["source_id"] not in existing_srcs:
                    target.setdefault("sources", []).append(src)
            aliases = (target["attributes"].get("aliases", {}).get("value") or [])
            if node_b.get("label") and node_b["label"] not in aliases and node_b["label"] != node_a.get("label"):
                aliases.append(node_b["label"])
                target["attributes"]["aliases"] = {"value": aliases, "event_date": None, "source_id": "merge"}
            target["updated_at"] = _now()
            kg_store.nodes[canonical_id] = target

        elif req.choice == "option_b":
            # Use new node (B) as canonical; add A's label as alias
            kg_store.apply_node(node_b)
            canonical_id = node_b["id"]
            target = kg_store.nodes[canonical_id]
            aliases = (target.get("attributes", {}).get("aliases", {}).get("value") or [])
            if node_a.get("label") and node_a["label"] not in aliases:
                aliases.append(node_a["label"])
                target.setdefault("attributes", {})["aliases"] = {"value": aliases, "event_date": None, "source_id": "merge"}

        else:  # keep_both → user confirmed they are different entities
            canonical_id = node_b["id"]
            kg_store.apply_node(node_b)

        # Remap pending edge_add items referencing node_b's provisional id → canonical
        if req.choice != "keep_both" and proposed_id:
            for p in data["pending"]:
                if p["status"] == "pending" and p["type"] == "edge_add":
                    edge = p.get("proposed", {})
                    if edge.get("source") == proposed_id:
                        edge["source"] = canonical_id
                    if edge.get("target") == proposed_id:
                        edge["target"] = canonical_id

        item["status"] = "resolved"
        item["resolution"] = {"choice": req.choice, "reason": req.reason}
        _save_pending(data)
        kg_store.save()
        return {"status": "resolved", "id": item_id, "choice": req.choice}
    # ── End merge resolution ─────────────────────────────────────────────────────

    conflict = item.get("conflict", {})
    event_date = conflict.get("option_a", {}).get("source", {}).get("date", "")

    if "field" in conflict:
        # Attribute conflict
        node = kg_store.nodes.get(conflict.get("entity_id", ""))
        if node and req.choice in ("option_a", "option_b"):
            chosen_val = conflict["option_a"]["value"] if req.choice == "option_a" else conflict["option_b"]["value"]
            node.setdefault("attributes", {})[conflict["field"]] = {"value": chosen_val, "event_date": event_date, "source_id": ""}
            node["updated_at"] = datetime.now(timezone.utc).isoformat()
            evolution_tracker.log({"event_date": event_date, "change_type": "conflict_resolved",
                "entity_id": conflict["entity_id"], "field": conflict["field"],
                "chosen": req.choice, "reason": req.reason})
    else:
        # Edge conflict
        if req.choice == "option_b" or req.choice == "keep_both":
            chosen_edge = conflict.get("option_b", {}).get("edge", {})
            if chosen_edge:
                kg_store.apply_edge(chosen_edge)
        if req.choice == "keep_both":
            chosen_edge_a = conflict.get("option_a", {}).get("edge", {})
            if chosen_edge_a:
                kg_store.apply_edge(chosen_edge_a)
        evolution_tracker.log({"event_date": event_date, "change_type": "conflict_resolved",
            "choice": req.choice, "reason": req.reason})

    item["status"] = "resolved"
    item["resolution"] = {"choice": req.choice, "reason": req.reason}
    _save_pending(data)
    kg_store.save()
    return {"status": "resolved", "id": item_id, "choice": req.choice}


class AIResolveRequest(BaseModel):
    instruction: str


@router.post("/pending/{item_id}/ai_resolve")
async def ai_resolve_conflict(item_id: str, req: AIResolveRequest):
    """Ask GPT-4o to suggest a resolution given a user instruction."""
    import os
    from openai import AsyncOpenAI

    data = _load_pending()
    item = next((p for p in data["pending"] if p["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Pending item not found")
    if item["type"] != "conflict":
        raise HTTPException(status_code=400, detail="Item is not a conflict")

    conflict = item.get("conflict", {})

    # Build a concise description of the conflict for the LLM
    if "field" in conflict:
        entity_id = conflict.get("entity_id", "?")
        node = kg_store.nodes.get(entity_id)
        entity_label = node["label"] if node else entity_id
        conflict_desc = (
            f"Attribute conflict on entity '{entity_label}' (id: {entity_id}), field: '{conflict['field']}'\n"
            f"Option A: {conflict.get('option_a', {}).get('value')} "
            f"(source: {conflict.get('option_a', {}).get('source', {}).get('title', 'unknown')})\n"
            f"Option B: {conflict.get('option_b', {}).get('value')} "
            f"(source: {conflict.get('option_b', {}).get('source', {}).get('title', 'unknown')})\n"
        )
        if conflict.get("option_a", {}).get("excerpt"):
            conflict_desc += f"Excerpt A: \"{conflict['option_a']['excerpt']}\"\n"
        if conflict.get("option_b", {}).get("excerpt"):
            conflict_desc += f"Excerpt B: \"{conflict['option_b']['excerpt']}\"\n"
    else:
        edge_a = conflict.get("option_a", {}).get("edge", {})
        edge_b = conflict.get("option_b", {}).get("edge", {})
        src_a = kg_store.nodes.get(edge_a.get("source", ""), {}).get("label", edge_a.get("source", "?"))
        tgt_a = kg_store.nodes.get(edge_a.get("target", ""), {}).get("label", edge_a.get("target", "?"))
        src_b = kg_store.nodes.get(edge_b.get("source", ""), {}).get("label", edge_b.get("source", "?"))
        tgt_b = kg_store.nodes.get(edge_b.get("target", ""), {}).get("label", edge_b.get("target", "?"))
        conflict_desc = (
            f"Edge conflict:\n"
            f"Option A: {src_a} —[{edge_a.get('label', '?')}]→ {tgt_a} "
            f"(source: {conflict.get('option_a', {}).get('source', {}).get('title', 'unknown')})\n"
            f"Option B: {src_b} —[{edge_b.get('label', '?')}]→ {tgt_b} "
            f"(source: {conflict.get('option_b', {}).get('source', {}).get('title', 'unknown')})\n"
        )
        if conflict.get("option_b", {}).get("excerpt"):
            conflict_desc += f"Excerpt B: \"{conflict['option_b']['excerpt']}\"\n"

    llm_assessment = conflict.get("llm_assessment", "")
    if llm_assessment:
        conflict_desc += f"\nPrevious AI assessment: {llm_assessment}"

    prompt = (
        f"You are resolving a knowledge graph conflict.\n\n"
        f"{conflict_desc}\n\n"
        f"User instruction: {req.instruction}\n\n"
        f"Based on the conflict details and the user's instruction, decide the resolution.\n"
        f"Respond with a JSON object: {{\"choice\": \"option_a\" | \"option_b\" | \"keep_both\", \"reasoning\": \"...\"}}\n"
        f"Only output valid JSON, nothing else."
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set")

    try:
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        result = json.loads(resp.choices[0].message.content)
        choice = result.get("choice", "keep_both")
        reasoning = result.get("reasoning", "")
        if choice not in ("option_a", "option_b", "keep_both"):
            choice = "keep_both"
        return {"choice": choice, "reasoning": reasoning}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI resolve failed: {e}")


@router.post("/pending/approve_all")
def approve_all_pending():
    data = _load_pending()
    count = 0
    for item in data["pending"]:
        if item["status"] == "pending" and item["type"] in ("node_add", "edge_add", "attribute_update"):
            event_date = (item.get("evidence", {}).get("source", {}).get("date", "") or
                         item.get("evidence", {}).get("source", {}).get("published_at", ""))
            source_id = ""
            if item["type"] == "node_add":
                kg_store.apply_node(item["proposed"])
                evolution_tracker.log({"event_date": event_date, "change_type": "node_added",
                    "entity_id": item["proposed"]["id"], "source_id": source_id})
            elif item["type"] == "edge_add":
                kg_store.apply_edge(item["proposed"])
                evolution_tracker.log({"event_date": event_date, "change_type": "edge_added",
                    "edge_id": item["proposed"].get("id", ""), "source_id": source_id})
            item["status"] = "approved"
            count += 1
    _save_pending(data)
    kg_store.save()
    return {"approved": count}


@router.delete("/pending")
def clear_pending():
    data = _load_pending()
    to_remove = [i for i in data["pending"] if i["status"] == "pending"]
    source_ids = {i["source_id"] for i in to_remove if i.get("source_id")}
    data["pending"] = [i for i in data["pending"] if i["status"] != "pending"]
    _save_pending(data)
    for sid in source_ids:
        kg_store.processed_sources.discard(sid)
    if source_ids:
        kg_store.save()
    return {"removed": len(to_remove)}


# ── Incoming document pool ────────────────────────────────────────────────────

INCOMING_FILE = pathlib.Path(__file__).parents[2] / "data" / "kg" / "incoming.json"


def _load_incoming() -> list:
    if not INCOMING_FILE.exists():
        return []
    with open(INCOMING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_incoming(data: list) -> None:
    INCOMING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INCOMING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class IncomingDocRequest(BaseModel):
    type: Literal["url", "text"] = "text"
    title: str = ""
    content: str = ""   # text body or URL
    url: str = ""


@router.get("/incoming")
def get_incoming():
    return {"incoming": _load_incoming()}


@router.post("/incoming")
def add_incoming(req: IncomingDocRequest):
    items = _load_incoming()
    doc_id = f"inc_{uuid.uuid4().hex[:10]}"
    item = {
        "id": doc_id,
        "type": req.type,
        "title": req.title or (req.url if req.type == "url" else req.content[:60] + "…"),
        "content": req.content,
        "url": req.url,
        "status": "queued",
        "added_at": _now(),
        "processed_at": None,
        "result": None,
    }
    items.append(item)
    _save_incoming(items)
    return item


@router.delete("/incoming")
def clear_incoming():
    _save_incoming([])
    return {"status": "cleared"}


@router.delete("/incoming/{doc_id}")
def delete_incoming(doc_id: str):
    items = _load_incoming()
    items = [i for i in items if i["id"] != doc_id]
    _save_incoming(items)
    return {"status": "deleted", "id": doc_id}


@router.post("/processed/{source_id}/reset")
def reset_processed(source_id: str):
    """Remove a source from the processed set so it can be re-ingested."""
    kg_store.processed_sources.discard(source_id)
    kg_store.save()
    return {"status": "reset", "source_id": source_id}


@router.get("/sources/{source_id}")
def get_source_meta(source_id: str):
    """Return metadata (title, url, date) for a stored source."""
    index = source_store._load_index()
    entry = index.get(source_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Source not found")
    return {k: entry.get(k) for k in ("source_id", "title", "url", "date", "news_site", "type", "ingested_at")}


@router.post("/incoming/{doc_id}/process")
async def process_incoming(doc_id: str, mode: str = "review", force: bool = False):
    items = _load_incoming()
    item = next((i for i in items if i["id"] == doc_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")
    if item["status"] == "processing":
        raise HTTPException(status_code=409, detail="Document is already being processed")

    item["status"] = "processing"
    _save_incoming(items)

    try:
        text = item["content"]
        url = item.get("url", "")

        # Fetch URL content if URL type
        if item["type"] == "url" and url and not text:
            import requests as req_lib
            from bs4 import BeautifulSoup
            try:
                resp = req_lib.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (compatible; TASA-KG-Bot/1.0)"})
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")

                # Remove boilerplate tags entirely
                for tag in soup(["script", "style", "nav", "header", "footer",
                                  "aside", "form", "noscript", "iframe", "svg",
                                  "button", "input", "select", "textarea"]):
                    tag.decompose()

                # Try to find the main article body first
                article = (soup.find("article") or
                           soup.find(attrs={"role": "main"}) or
                           soup.find("main") or
                           soup.find(class_=lambda c: c and any(
                               x in c for x in ("article", "content", "story", "post", "body"))) or
                           soup.find("body") or soup)

                # Extract text from meaningful tags only
                parts = []
                title_tag = soup.find("title")
                if title_tag:
                    parts.append(title_tag.get_text(strip=True))
                for tag in article.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "td"]):
                    t = tag.get_text(separator=" ", strip=True)
                    if len(t) > 30:  # skip very short fragments (nav links, etc.)
                        parts.append(t)

                text = "\n\n".join(parts)
                text = text[:25000]

                # Auto-fill title from <title> if not provided
                if not item.get("title") and title_tag:
                    item["title"] = title_tag.get_text(strip=True)[:120]

            except Exception as e:
                item["status"] = "error"
                item["result"] = {"error": f"Failed to fetch URL: {e}"}
                _save_incoming(items)
                return item

        source_id = _source_id_from_url(url) if url else _source_id_from_text(text)
        source = {
            "type": "report",
            "title": item.get("title", ""),
            "url": url,
            "date": item["added_at"][:10],
        }

        result = await _run_ingest(text, source, source_id, mode, force=force)
        item["status"] = "done"
        item["processed_at"] = _now()
        item["result"] = result

    except Exception as e:
        item["status"] = "error"
        item["result"] = {"error": str(e)}

    _save_incoming(items)
    return item


# ── Schema proposals ──────────────────────────────────────────────────────────

@router.get("/satellite/{identifier}")
def get_satellite_info(identifier: str):
    """Return satellite info by node ID or norad_id attribute. Used as fallback by frontend."""
    node = kg_store.nodes.get(identifier)
    if not node:
        # Search by norad_id attribute
        for n in kg_store.nodes.values():
            attrs = n.get("attributes", {})
            norad = attrs.get("norad_id")
            val = norad.get("value") if isinstance(norad, dict) else norad
            if val is not None and str(val) == identifier:
                node = n
                break
    if not node:
        raise HTTPException(status_code=404, detail="Satellite not found in KG")

    attrs = node.get("attributes", {})
    def attr_val(key):
        v = attrs.get(key)
        if not v:
            return ""
        val = v.get("value") if isinstance(v, dict) else v
        return str(val) if val is not None else ""

    raw_norad = attr_val("norad_id")
    # Only expose noradId if it looks like a real NORAD catalog number (all digits, ≤ 99999)
    display_norad = raw_norad if raw_norad and raw_norad.isdigit() and int(raw_norad) <= 99999 else ""
    notos_id = attr_val("notos_id")
    return {
        "nodeId": node["id"],
        "noradId": display_norad,
        "notosId": notos_id,
        "name": node.get("label", node["id"]),
        "type": node.get("type", ""),
        "launchDate": attr_val("launch_date"),
        "manufacturer": attr_val("manufacturer"),
        "operator": attr_val("operator"),
        "mission": attr_val("mission"),
        "orbitType": attr_val("orbit_type"),
        "altitudeKm": attr_val("altitude_km"),
        "imageUrl": "",
        "description": attr_val("description"),
        "newsKeywords": attr_val("news_keywords"),
        "source": "kg",
    }


class SatelliteCreateIn(BaseModel):
    noradId: str
    name: str
    line1: str
    line2: str
    type: str = "Satellite"
    newsKeywords: str = ""


@router.post("/satellites")
def create_satellite(body: SatelliteCreateIn):
    """Create a satellite KG node and register its TLE in one call."""
    from modules.propagation import tle_store
    import main as _main

    norad = body.noradId.strip()
    if not norad.isdigit():
        raise HTTPException(status_code=400, detail="noradId must be numeric")

    sat_type = body.type if schema_manager.is_valid_type(body.type) else "Satellite"
    inferred = schema_manager.get_ancestors(sat_type)

    attrs: dict = {
        "norad_id": {"value": norad, "event_date": None, "source_id": "manual"},
    }
    if body.newsKeywords.strip():
        attrs["news_keywords"] = {"value": body.newsKeywords.strip(), "event_date": None, "source_id": "manual"}

    now = _now()
    node = {
        "id": norad,
        "label": body.name.strip(),
        "type": sat_type,
        "inferred_types": inferred,
        "attributes": attrs,
        "sources": [],
        "created_at": now,
        "updated_at": now,
    }

    if norad in kg_store.nodes:
        raise HTTPException(status_code=409, detail=f"Satellite {norad} already exists")

    kg_store.nodes[norad] = node
    kg_store.save()

    # Register TLE so propagation works immediately
    tle_store.upsert(norad, body.name.strip(), body.line1.strip(), body.line2.strip())

    # Pre-compute positions and add to cache
    from datetime import timedelta
    from modules.propagation import sgp4_propagator
    from datetime import timezone as _tz
    start = datetime.now(_tz.utc).replace(second=0, microsecond=0) - timedelta(hours=12)
    end = start + timedelta(hours=24)
    positions = sgp4_propagator.get_positions(body.line1.strip(), body.line2.strip(), start, end, step_seconds=60)
    _main._position_cache[norad] = [
        {"lat": p.lat, "lon": p.lon, "alt": p.alt, "timestamp": p.timestamp}
        for p in positions
    ]

    evolution_tracker.log({
        "event_date": now,
        "ingested_at": now,
        "change_type": "node_added",
        "entity_id": norad,
        "source_id": "manual",
    })

    return {"nodeId": norad, "label": node["label"], "type": sat_type, "positionsComputed": len(positions)}


@router.patch("/nodes/{node_id}")
def update_node(node_id: str, body: dict):
    """Update label and/or type of an existing KG node. Recalculates inferred_types."""
    node = kg_store.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if "label" in body and body["label"]:
        node["label"] = body["label"].strip()
    if "type" in body and body["type"]:
        new_type = body["type"].strip()
        if not schema_manager.is_valid_type(new_type):
            raise HTTPException(status_code=400, detail=f"Unknown type: {new_type}")
        node["type"] = new_type
        node["inferred_types"] = schema_manager.get_ancestors(new_type)
    node["updated_at"] = _now()
    kg_store.save()
    return {"node_id": node_id, "label": node["label"], "type": node["type"], "inferred_types": node["inferred_types"]}


@router.delete("/nodes/{node_id}")
def delete_node(node_id: str):
    """Remove a node and all its edges from the KG."""
    if node_id not in kg_store.nodes:
        raise HTTPException(status_code=404, detail="Node not found")
    del kg_store.nodes[node_id]
    # Remove edges that reference this node
    to_del = [eid for eid, e in kg_store.edges.items()
              if e.get("source") == node_id or e.get("target") == node_id]
    for eid in to_del:
        del kg_store.edges[eid]
    kg_store.save()
    return {"deleted": node_id, "edges_removed": len(to_del)}


class MergeRequest(BaseModel):
    canonical: str
    overrides: dict = {}


@router.post("/nodes/{node_id}/merge/{other_id}")
def merge_nodes_endpoint(node_id: str, other_id: str, req: MergeRequest):
    """Merge two nodes. canonical= which node_id to keep; overrides= per-field conflict resolutions."""
    if node_id not in kg_store.nodes:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    if other_id not in kg_store.nodes:
        raise HTTPException(status_code=404, detail=f"Node {other_id} not found")
    if req.canonical not in (node_id, other_id):
        raise HTTPException(status_code=400, detail="canonical must be one of the two node IDs")
    duplicate_id = other_id if req.canonical == node_id else node_id
    try:
        result = kg_store.merge_nodes(req.canonical, duplicate_id, req.overrides)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    evolution_tracker.log({
        "event_date": _now()[:10],
        "change_type": "nodes_merged",
        "entity_id": req.canonical,
        "merged_from": duplicate_id,
        "source_id": "",
    })
    return result


@router.delete("/edges/{edge_id}")
def delete_edge(edge_id: str):
    """Remove an edge from the KG."""
    if edge_id not in kg_store.edges:
        raise HTTPException(status_code=404, detail="Edge not found")
    del kg_store.edges[edge_id]
    kg_store.save()
    return {"deleted": edge_id}


@router.patch("/edges/{edge_id}")
def update_edge(edge_id: str, body: dict):
    """Update an edge's label. Body: {label: str}. Re-keys the edge if label changes."""
    edge = kg_store.edges.get(edge_id)
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")
    new_label = (body.get("label") or "").strip()
    if not new_label:
        raise HTTPException(status_code=422, detail="label is required")
    if new_label == edge.get("label"):
        return {"id": edge_id, "label": new_label}
    # Label change → new id; delete old, insert new
    del kg_store.edges[edge_id]
    updated = {**edge, "label": new_label}
    updated.pop("id", None)
    kg_store.apply_edge(updated)
    new_id = updated["id"]
    kg_store.save()
    return {"id": new_id, "label": new_label}


@router.patch("/nodes/{node_id}/attribute")
def update_node_attribute(node_id: str, body: dict):
    """Update a single attribute on an existing KG node. Body: {key: str, value: any}"""
    node = kg_store.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    key = body.get("key")
    value = body.get("value")
    if not key:
        raise HTTPException(status_code=400, detail="Missing 'key'")
    node.setdefault("attributes", {})[key] = {
        "value": value,
        "event_date": None,
        "source_id": "manual",
    }
    node["updated_at"] = _now()
    kg_store.save()
    return {"node_id": node_id, "key": key, "value": value}


@router.get("/schema/types")
def get_schema_types():
    return {"types": schema_manager.get_all_types()}


@router.get("/schema/tree")
def get_schema_tree():
    return {"tree": schema_manager.get_tree()}


@router.patch("/pending/{item_id}")
def update_pending_item(item_id: str, body: dict):
    data = _load_pending()
    item = next((p for p in data["pending"] if p["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Pending item not found")
    if "type" in body and item.get("proposed"):
        new_type = body["type"]
        item["proposed"]["type"] = new_type
        item["proposed"]["inferred_types"] = schema_manager.get_ancestors(new_type)
    _save_pending(data)
    return item


@router.get("/schema/proposals")
def get_schema_proposals():
    return {"proposals": list(_load_proposed_types().values())}


@router.post("/schema/proposals/{type_name}/reject")
def reject_schema_proposal(type_name: str, map_to: str = ""):
    proposals = _load_proposed_types()
    if type_name not in proposals:
        raise HTTPException(status_code=404, detail="Proposal not found")
    proposals[type_name]["schema_status"] = "rejected"
    if map_to:
        proposals[type_name]["mapped_to"] = map_to
    _save_proposed_types(proposals)
    return {"status": "rejected", "type": type_name, "mapped_to": map_to}


# ── NORAD assignment and matching ─────────────────────────────────────────────

@router.post("/nodes/{node_id}/assign-norad")
def assign_norad(node_id: str, body: dict):
    """Assign a confirmed NORAD ID to a satellite node, fetch TLE, and pre-compute positions."""
    import urllib.request as _urllib_req
    import json as _json2

    norad = str(body.get("norad_id", "")).strip()
    if not norad.isdigit():
        raise HTTPException(status_code=400, detail="norad_id must be numeric")
    node = kg_store.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    node.setdefault("attributes", {})["norad_id"] = {
        "value": norad, "event_date": None, "source_id": "manual"
    }
    node["updated_at"] = _now()
    kg_store.save()

    from api.routes_propagation import _fetch_and_cache_tle
    import main as _main
    from datetime import timedelta
    from modules.propagation import tle_store, sgp4_propagator
    from datetime import timezone as _tz

    _fetch_and_cache_tle(norad)
    sat = tle_store.get(norad)
    positions_computed = 0
    if sat:
        now_dt = datetime.now(_tz.utc).replace(second=0, microsecond=0)
        positions = sgp4_propagator.get_positions(
            sat.line1, sat.line2,
            now_dt - timedelta(hours=12),
            now_dt + timedelta(hours=12),
            60,
        )
        _main._position_cache[norad] = [
            {"lat": p.lat, "lon": p.lon, "alt": p.alt, "timestamp": p.timestamp}
            for p in positions
        ]
        positions_computed = len(positions)

    return {
        "node_id": node_id,
        "norad_id": norad,
        "tle_found": sat is not None,
        "positions_computed": positions_computed,
    }


@router.get("/nodes/{node_id}/find-norad")
def find_norad_candidates(node_id: str):
    """Query CelesTrak SATCAT to find NORAD candidates matching this node's orbital parameters."""
    import urllib.request as _urllib_req
    import json as _json2
    from datetime import date as _date, timedelta as _td

    node = kg_store.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    attrs = node.get("attributes", {})
    incl_attr = attrs.get("inclination")
    period_attr = attrs.get("orbital_period")
    if not incl_attr or not period_attr:
        raise HTTPException(
            status_code=400,
            detail="Node missing inclination or orbital_period attributes — process a NOTOS report first",
        )

    def _extract(v):
        if isinstance(v, dict):
            return v.get("value")
        return v

    try:
        incl = float(_extract(incl_attr))
        period = float(_extract(period_attr))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="inclination / orbital_period are not numeric")

    # Get launch date from stored launch events
    from modules.events.event_store import event_store as _evt_store
    launch_evts = [e for e in _evt_store.get_by_satellite(node_id) if e.get("type") == "launch"]
    if not launch_evts:
        raise HTTPException(status_code=400, detail="No launch event found for this satellite — ingest the NOTOS report first")

    launch_date_str = launch_evts[0]["event_date"][:10]  # YYYY-MM-DD
    try:
        d = _date.fromisoformat(launch_date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid launch event date: {launch_date_str}")

    start = (d - _td(days=3)).isoformat()
    end = (d + _td(days=3)).isoformat()
    url = f"https://celestrak.org/satcat/records.php?LAUNCH={start}--{end}&FORMAT=json"

    try:
        req = _urllib_req.Request(url, headers={"User-Agent": "TASA/1.0"})
        with _urllib_req.urlopen(req, timeout=12) as r:
            records = _json2.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"CelesTrak fetch failed: {e}")

    if not isinstance(records, list):
        raise HTTPException(status_code=502, detail="Unexpected CelesTrak response format")

    candidates = []
    for rec in records:
        try:
            c_incl = float(rec.get("INCLINATION", 0) or 0)
            c_period = float(rec.get("PERIOD", 0) or 0)
        except (TypeError, ValueError):
            continue
        if c_period <= 0:
            continue
        incl_diff = abs(c_incl - incl)
        period_diff = abs(c_period - period)
        if incl_diff <= 0.5 and period_diff <= 0.5:
            score = round(1.0 - (incl_diff / 0.5) * 0.5 - (period_diff / 0.5) * 0.5, 3)
            candidates.append({
                "norad_id": str(rec.get("NORAD_CAT_ID", "")),
                "name": rec.get("SATNAME", ""),
                "inclination": c_incl,
                "period": c_period,
                "launch_date": rec.get("LAUNCH_DATE", ""),
                "score": score,
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]


# ── Satellite tag enrichment ──────────────────────────────────────────────────

_UCS_PATH = pathlib.Path(__file__).parents[2] / "data" / "reference" / "UCS-Satellite-Database 5-1-2023.csv"

# Known military-adjacent Chinese/Russian org keywords
_MILITARY_ORG_KEYWORDS = [
    "casc", "cast", "plasat", "pla", "space and missile",
    "roscosmos", "khrunichev", "iss reshetnev",
    "ministry of defence", "department of defense",
]


def _load_ucs_data() -> dict[str, dict]:
    """Load UCS satellite database, keyed by NORAD number."""
    import csv as _csv
    data: dict[str, dict] = {}
    if not _UCS_PATH.exists():
        return data
    with open(_UCS_PATH, encoding="utf-8-sig", errors="replace") as f:
        for row in _csv.DictReader(f):
            norad = row.get("NORAD Number", "").strip()
            if norad:
                data[norad] = row
    return data


def _infer_satellite_tags(
    node_id: str,
    node: dict,
    ucs: dict | None,
    edges_by_source: dict[str, list],
) -> tuple[str | None, str | None]:
    """Return (new_type, new_country) inferred from UCS + KG graph, or None if not determinable."""
    attrs = node.get("attributes") or {}
    existing_country = (attrs.get("country") or {}).get("value") if isinstance(attrs.get("country"), dict) else attrs.get("country")

    # ── Country ──
    new_country: str | None = None
    if not existing_country:
        if ucs:
            raw_country = (ucs.get("Country of Operator/Owner") or "").strip() or None
            new_country = _normalize_country(raw_country) if raw_country else None
        if not new_country:
            for edge in edges_by_source.get(node_id, []):
                if edge.get("label") == "operatedBy":
                    org = kg_store.nodes.get(edge.get("target", ""))
                    if org:
                        org_attrs = org.get("attributes") or {}
                        for field in ("country_of_origin", "country", "operator_country"):
                            val = org_attrs.get(field)
                            if isinstance(val, dict):
                                val = val.get("value")
                            if val:
                                raw_val = str(val).strip()
                                new_country = _normalize_country(raw_val)
                                break
                if new_country:
                    break

    # ── Type ──
    new_type: str | None = None
    users = (ucs.get("Users") or "").strip() if ucs else ""
    purpose = (ucs.get("Purpose") or "").strip() if ucs else ""
    country = new_country or existing_country or ""

    if users == "Military":
        new_type = "MilitarySatellite"
    elif users == "Commercial":
        new_type = "CommercialSatellite"
    elif users == "Government":
        # Check operator for military affiliation
        is_military = False
        for edge in edges_by_source.get(node_id, []):
            if edge.get("label") == "operatedBy":
                org = kg_store.nodes.get(edge.get("target", ""))
                if org:
                    if org.get("type") == "MilitaryUnit":
                        is_military = True
                        break
                    org_lbl = org.get("label", "").lower()
                    if any(kw in org_lbl for kw in _MILITARY_ORG_KEYWORDS):
                        is_military = True
                        break
        # China/Russia government satellites with tech-dev purpose → military by convention
        if not is_military and country in ("China", "Russia") and (
            "Technology Development" in purpose or "Space Science" in purpose
        ):
            is_military = True
        new_type = "MilitarySatellite" if is_military else "CivilSatellite"

    return new_type, new_country


@router.post("/enrich/satellite-tags")
def enrich_satellite_tags():
    """Propose type and country updates for base-Satellite nodes using UCS DB + KG graph."""
    ucs_data = _load_ucs_data()

    # Build edge index: source_node_id → list of edges
    edges_by_source: dict[str, list] = {}
    for edge in kg_store.edges.values():
        edges_by_source.setdefault(edge.get("source", ""), []).append(edge)

    pending_data = _load_pending()
    # Track which (entity_id, field) pairs already have pending proposals to avoid dupes
    already_pending: set[tuple[str, str]] = {
        (p["entity_id"], p["field"])
        for p in pending_data["pending"]
        if p.get("type") == "attribute_update" and p.get("status") == "pending"
    }

    new_proposals: list[dict] = []
    now_str = _now()

    for node_id, node in kg_store.nodes.items():
        if node.get("type") != "Satellite":
            continue

        attrs = node.get("attributes") or {}
        norad = str((attrs.get("norad_id") or {}).get("value", "") or "").strip()
        ucs = ucs_data.get(norad) if norad else None

        new_type, new_country = _infer_satellite_tags(node_id, node, ucs, edges_by_source)

        source_desc = f"UCS Satellite Database (NORAD {norad})" if ucs else "KG operator relationships"
        users = (ucs.get("Users") or "") if ucs else ""
        purpose = (ucs.get("Purpose") or "") if ucs else ""

        if new_country and (node_id, "country") not in already_pending:
            existing = (attrs.get("country") or {}).get("value") if isinstance(attrs.get("country"), dict) else attrs.get("country")
            new_proposals.append({
                "id": f"enrich_{uuid.uuid4().hex[:8]}",
                "type": "attribute_update",
                "status": "pending",
                "entity_id": node_id,
                "field": "country",
                "old_value": existing,
                "new_value": new_country,
                "evidence": {
                    "excerpt": f"Country of Operator/Owner: {new_country}",
                    "source": {"source_id": "ucs_enrichment", "title": source_desc},
                },
                "llm_assessment": f"Source: {source_desc}",
                "created_at": now_str,
            })

        if new_type and (node_id, "type") not in already_pending:
            new_proposals.append({
                "id": f"enrich_{uuid.uuid4().hex[:8]}",
                "type": "attribute_update",
                "status": "pending",
                "entity_id": node_id,
                "field": "type",
                "old_value": "Satellite",
                "new_value": new_type,
                "evidence": {
                    "excerpt": f"Users: {users} · Purpose: {purpose}",
                    "source": {"source_id": "ucs_enrichment", "title": source_desc},
                },
                "llm_assessment": f"Inferred: Users={users or 'n/a'}, Purpose={purpose or 'n/a'}, Country={new_country or 'n/a'}",
                "created_at": now_str,
            })

    if new_proposals:
        pending_data["pending"].extend(new_proposals)
        _save_pending(pending_data)

    return {
        "proposed": len(new_proposals),
        "satellites_checked": sum(1 for n in kg_store.nodes.values() if n.get("type") == "Satellite"),
    }


# ── Satellite relation enrichment (launchedFrom / operatedBy / manufacturedBy) ──

# Canonical launch site names — substring match on UCS "Launch Site" value
_LAUNCH_SITE_CANONICAL: dict[str, str] = {
    "jiuquan": "Jiuquan Satellite Launch Center",
    "xichang": "Xichang Satellite Launch Center",
    "taiyuan": "Taiyuan Satellite Launch Center",
    "wenchang": "Wenchang Space Launch Site",
    "cape canaveral": "Cape Canaveral Space Launch Complex",
    "kennedy": "Kennedy Space Center",
    "vandenberg": "Vandenberg Space Force Base",
    "baikonur": "Baikonur Cosmodrome",
    "satish dhawan": "Satish Dhawan Space Centre",
    "sriharikota": "Satish Dhawan Space Centre",
    "kourou": "Guiana Space Centre",
    "plesetsk": "Plesetsk Cosmodrome",
    "vostochny": "Vostochny Cosmodrome",
}

def _canonical_launch_site(raw: str) -> str:
    low = raw.lower()
    for key, canonical in _LAUNCH_SITE_CANONICAL.items():
        if key in low:
            return canonical
    return raw.strip()


def _find_existing_node(label: str, node_type_hint: str) -> str | None:
    """Find an existing KG node matching label (case-insensitive exact or close match)."""
    label_low = label.lower().strip()
    for nid, node in kg_store.nodes.items():
        all_types = [node.get("type", "")] + (node.get("inferred_types") or [])
        if not any(node_type_hint in t or t in node_type_hint for t in all_types if t):
            continue
        if node.get("label", "").lower().strip() == label_low:
            return nid
        # Also check aliases attribute
        aliases_attr = (node.get("attributes") or {}).get("aliases")
        if isinstance(aliases_attr, dict):
            aliases = aliases_attr.get("value") or []
        elif isinstance(aliases_attr, list):
            aliases = aliases_attr
        else:
            aliases = []
        if any(str(a).lower().strip() == label_low for a in aliases):
            return nid
    return None


def _make_node_proposal(label: str, node_type: str, extra_attrs: dict, source_desc: str, now_str: str) -> tuple[str, dict]:
    """Return (node_id, pending_item) for a new node proposal."""
    import re as _re
    node_id = _re.sub(r"[^\w]", "_", label.lower())[:40].strip("_")
    inferred = schema_manager.get_ancestors(node_type)
    node = {
        "id": node_id,
        "label": label,
        "type": node_type,
        "inferred_types": inferred,
        "attributes": {k: {"value": v, "event_date": None, "source_id": "ucs_enrichment"} for k, v in extra_attrs.items() if v},
        "sources": [],
    }
    item = {
        "id": f"enrich_{uuid.uuid4().hex[:8]}",
        "type": "node_add",
        "status": "pending",
        "proposed": node,
        "evidence": {"excerpt": f"Auto-enriched from UCS database", "source": {"source_id": "ucs_enrichment", "title": source_desc}},
        "llm_assessment": f"Source: {source_desc}",
        "created_at": now_str,
    }
    return node_id, item


@router.post("/enrich/satellite-relations")
def enrich_satellite_relations():
    """Propose missing launchedFrom, operatedBy, manufacturedBy edges using UCS database."""
    ucs_data = _load_ucs_data()

    # Existing edges grouped by (source, label) → set of targets
    existing_rels: dict[tuple[str, str], set[str]] = {}
    for edge in kg_store.edges.values():
        key = (edge.get("source", ""), edge.get("label", ""))
        existing_rels.setdefault(key, set()).add(edge.get("target", ""))

    pending_data = _load_pending()
    # Track already-pending edge proposals and node proposals to avoid dupes
    pending_node_labels: set[str] = set()
    pending_edge_keys: set[tuple[str, str, str]] = set()
    for p in pending_data["pending"]:
        if p.get("status") != "pending":
            continue
        if p.get("type") == "node_add":
            pending_node_labels.add((p.get("proposed") or {}).get("label", "").lower())
        elif p.get("type") == "edge_add":
            pr = p.get("proposed") or {}
            pending_edge_keys.add((pr.get("source", ""), pr.get("label", ""), pr.get("target", "")))

    new_proposals: list[dict] = []
    now_str = _now()
    # Track nodes we're proposing in this run so we don't duplicate within one call
    proposing_nodes: dict[str, str] = {}  # label.lower() → node_id

    def _get_or_propose_node(label: str, node_type: str, extra_attrs: dict, source_desc: str) -> str | None:
        if not label.strip():
            return None
        label_low = label.lower().strip()
        # 1. Already in KG
        existing = _find_existing_node(label, node_type)
        if existing:
            return existing
        # 2. Already proposing in this run
        if label_low in proposing_nodes:
            return proposing_nodes[label_low]
        # 3. Already pending
        if label_low in pending_node_labels:
            # Find its proposed id from pending
            for p in pending_data["pending"]:
                if p.get("type") == "node_add" and (p.get("proposed") or {}).get("label", "").lower() == label_low:
                    return (p.get("proposed") or {}).get("id", "")
            return None
        # 4. Propose new node
        node_id, item = _make_node_proposal(label, node_type, extra_attrs, source_desc, now_str)
        new_proposals.append(item)
        proposing_nodes[label_low] = node_id
        return node_id

    for node_id, node in kg_store.nodes.items():
        all_types = [node.get("type", "")] + (node.get("inferred_types") or [])
        if not any(t == "Satellite" or (isinstance(t, str) and t.endswith("Satellite")) for t in all_types):
            continue

        attrs = node.get("attributes") or {}
        norad = str((attrs.get("norad_id") or {}).get("value", "") or "").strip()
        ucs = ucs_data.get(norad) if norad else None
        if not ucs:
            continue

        source_desc = f"UCS Satellite Database (NORAD {norad})"

        def _propose_edge(predicate: str, target_id: str) -> None:
            key = (node_id, predicate, target_id)
            already = target_id in existing_rels.get((node_id, predicate), set())
            if already or key in pending_edge_keys:
                return
            new_proposals.append({
                "id": f"enrich_{uuid.uuid4().hex[:8]}",
                "type": "edge_add",
                "status": "pending",
                "proposed": {"source": node_id, "label": predicate, "target": target_id, "sources": []},
                "evidence": {"excerpt": ucs.get("Name of Satellite, Alternate Names", "")[:80], "source": {"source_id": "ucs_enrichment", "title": source_desc}},
                "llm_assessment": f"Source: {source_desc}",
                "created_at": now_str,
            })
            pending_edge_keys.add(key)

        # ── launchedFrom ──
        if not existing_rels.get((node_id, "launchedFrom")):
            raw_site = (ucs.get("Launch Site") or "").strip()
            if raw_site:
                canonical_site = _canonical_launch_site(raw_site)
                site_id = _get_or_propose_node(canonical_site, "LaunchSite", {}, source_desc)
                if site_id:
                    _propose_edge("launchedFrom", site_id)

        # ── operatedBy ──
        if not existing_rels.get((node_id, "operatedBy")):
            raw_op = (ucs.get("Operator/Owner") or "").strip()
            country_op = (ucs.get("Country of Operator/Owner") or "").strip()
            users = (ucs.get("Users") or "").strip()
            if raw_op:
                org_type = "MilitaryUnit" if users == "Military" else (
                    "SpaceAgency" if any(k in raw_op.lower() for k in ("space agency", "national space", "nasa", "cnsa", "isro", "jaxa", "esa")) else "Company"
                )
                op_id = _get_or_propose_node(raw_op, org_type, {"country": country_op}, source_desc)
                if op_id:
                    _propose_edge("operatedBy", op_id)

        # ── manufacturedBy ──
        if not existing_rels.get((node_id, "manufacturedBy")):
            raw_mfg = (ucs.get("Contractor") or "").strip()
            country_mfg = (ucs.get("Country of Contractor") or "").strip()
            # Skip if same as operator (already handled above) unless different name
            if raw_mfg:
                mfg_id = _get_or_propose_node(raw_mfg, "Company", {"country": country_mfg}, source_desc)
                if mfg_id:
                    _propose_edge("manufacturedBy", mfg_id)

        # ── operatingCountry ──
        if not existing_rels.get((node_id, "operatingCountry")):
            raw_country = (ucs.get("Country of Operator/Owner") or "").strip()
            if raw_country:
                canonical = _normalize_country(raw_country)
                if canonical:
                    country_id = _get_or_propose_node(canonical, "Country", {"name": canonical}, source_desc)
                    if country_id:
                        _propose_edge("operatingCountry", country_id)

    if new_proposals:
        pending_data["pending"].extend(new_proposals)
        _save_pending(pending_data)

    edge_count = sum(1 for p in new_proposals if p["type"] == "edge_add")
    node_count = sum(1 for p in new_proposals if p["type"] == "node_add")
    return {"proposed": len(new_proposals), "edges": edge_count, "nodes": node_count}


# ── Normalize existing country names ──

@router.post("/normalize/country-names")
def normalize_country_names():
    """Normalize all country name variants in the KG to canonical form.
    Updates country, operator_country, country_of_operator attributes in-place."""
    updated_count = 0

    for node in kg_store.nodes.values():
        attrs = node.get("attributes") or {}
        changed = False

        for field in ("country", "operator_country", "country_of_operator"):
            if field not in attrs:
                continue

            attr_val = attrs[field]
            if isinstance(attr_val, dict):
                current = attr_val.get("value")
            else:
                current = attr_val

            if current:
                normalized = _normalize_country(str(current))
                if normalized != str(current):
                    # Update the attribute
                    if isinstance(attr_val, dict):
                        attrs[field]["value"] = normalized
                    else:
                        attrs[field] = normalized
                    changed = True

        if changed:
            updated_count += 1
            node["attributes"] = attrs

    # Save to KG
    kg_store.save()

    return {
        "message": f"Normalized country names in {updated_count} nodes",
        "count": updated_count,
    }
