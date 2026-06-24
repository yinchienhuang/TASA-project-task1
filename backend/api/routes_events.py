"""
Satellite event API routes: store and retrieve maneuver / photometric change events.
"""
import hashlib
import json
import pathlib
import re
import uuid

from fastapi import APIRouter, HTTPException, Query

from modules.events.event_store import event_store
from modules.events.jco_extractor import extract_events_from_jco
from modules.events.notam_extractor import extract_launch_events
from modules.knowledge_graph import source_store
from modules.knowledge_graph.source_store import SOURCES_DIR
from modules.knowledge_graph.mhtml_reader import read_mhtml

_PENDING_FILE = pathlib.Path(__file__).parents[2] / "data" / "kg" / "pending.json"


def _load_pending_items() -> list[dict]:
    if not _PENDING_FILE.exists():
        return []
    return json.loads(_PENDING_FILE.read_text(encoding="utf-8")).get("pending", [])


def _append_pending_proposals(proposals: list[dict]) -> None:
    """Append proposals through routes_kg's cache so the in-memory state stays consistent."""
    if not proposals:
        return
    from api.routes_kg import _load_pending, _save_pending
    pd = _load_pending()
    pd["pending"].extend(proposals)
    _save_pending(pd)

router = APIRouter(prefix="/api/events", tags=["events"])

JCO_DIR = pathlib.Path(__file__).parents[2] / "data" / "JCO report"

# ---------------------------------------------------------------------------
# JCO multi-update section annotator
# ---------------------------------------------------------------------------
# JCO reports contain multiple timestamped update sections separated by ===
# dividers. The LATEST update is at the top; earlier sections are initial
# detections that have been superseded. Annotating them lets the LLM know
# which section takes precedence.
# ---------------------------------------------------------------------------

_SECTION_SEP_RE = re.compile(r'={5,}')


def _annotate_jco_sections(text: str) -> str:
    """Split JCO report text on ===== dividers and label each section.

    The first section (top of document) is the latest update; subsequent
    sections are progressively older initial detections.
    """
    sections = _SECTION_SEP_RE.split(text)
    if len(sections) == 1:
        return text  # no separators — single-section report, nothing to do

    labeled: list[str] = []
    for i, section in enumerate(sections):
        s = section.strip()
        if not s:
            continue
        if i == 0:
            label = "[LATEST UPDATE — primary source for all events; values here supersede earlier sections]"
        else:
            label = f"[EARLIER UPDATE {i} — superseded by the latest update above; only extract if event is not already covered in the latest section]"
        labeled.append(f"{label}\n\n{s}")

    return ("\n\n" + "=" * 50 + "\n\n").join(labeled)


# ---------------------------------------------------------------------------
# Deterministic PAIR section parser
# ---------------------------------------------------------------------------
# PAIR rows look like:
#   64467 | COSMOS 2589 (14F166A) | GEO-GSO | Operator (Country) | Status |
#   Users | Mission | DD/MM/YYYY (age) | [lifetime |] Intel desc | Propulsion status |
#   Propulsion type | Associated sats | Source: ...
# ---------------------------------------------------------------------------

_PAIR_ROW_RE = re.compile(r'^\s*(\d{4,6})\s*\|(.+)', re.MULTILINE)

def _parse_pair_rows(text: str) -> list[dict]:
    """Extract structured satellite data from PAIR pipe-delimited rows."""
    results = []
    for m in _PAIR_ROW_RE.finditer(text):
        norad = m.group(1).strip()
        rest = m.group(0).strip()
        cols = [c.strip() for c in rest.split('|')]
        if len(cols) < 8:
            continue

        # col[0] = NORAD, col[1] = name (with optional designation in parens)
        name_raw = cols[1].strip()
        designation = None
        dm = re.search(r'\(([^)]+)\)', name_raw)
        if dm and re.search(r'[A-Z0-9]{3,}', dm.group(1)):
            designation = dm.group(1).strip()

        # col[2] = orbit type
        orbit_type = cols[2].strip()

        # col[3] = Operator (Country) — extract country from last parens
        operator_raw = cols[3].strip()
        country = None
        cm = re.search(r'\(([^)]+)\)\s*$', operator_raw)
        if cm:
            country = cm.group(1).strip()
            operator = operator_raw[:cm.start()].strip().rstrip('-').strip()
        else:
            operator = operator_raw

        # col[4] = status
        status = cols[4].strip()
        maneuverable = "Yes" if re.search(r'maneuver', status, re.IGNORECASE) else (
            "No" if re.search(r'non-maneuver|not maneuver', status, re.IGNORECASE) else "Unknown"
        )

        # col[5] = users
        users = cols[5].strip()

        # col[6] = mission
        mission = cols[6].strip()

        # col[7] = launch date + age  e.g. "23/12/2021 (4.43 years old)"
        launch_date = None
        date_m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', cols[7])
        if date_m:
            day, mon, year = date_m.groups()
            launch_date = f"{year}-{int(mon):02d}-{int(day):02d}"

        # Work from the end for reliable field detection
        # Last col is usually "Source: ..."
        # Second-to-last: associated satellites
        # Third-to-last: propulsion type
        # Fourth-to-last: propulsion status
        # Fifth-to-last: intel description (may span multiple cols if commas in text)
        cols_end = [c for c in cols if not c.lower().startswith('source')]
        if not cols_end:
            cols_end = cols

        propulsion_type = None
        propulsion_status = None
        intel_desc = None

        # Find propulsion columns searching from end
        prop_idx = None
        for i in range(len(cols_end) - 1, 0, -1):
            if re.search(r'propulsion|chemical|electric|hydrazine|bipropellant|monopropellant', cols_end[i], re.IGNORECASE):
                prop_idx = i
                break

        if prop_idx is not None:
            propulsion_type = cols_end[prop_idx].strip()
            # propulsion status is just before type
            if prop_idx > 0 and re.search(r'propulsion|yes|no\b', cols_end[prop_idx - 1], re.IGNORECASE):
                propulsion_status = cols_end[prop_idx - 1].strip()
            # intel description = everything between launch date col and propulsion status
            desc_start = 8  # after launch date col
            if prop_idx > desc_start:
                desc_end = prop_idx - 1 if propulsion_status else prop_idx
                intel_desc = ' | '.join(cols_end[desc_start:desc_end]).strip() or None
        else:
            # No explicit propulsion found — grab remaining text as intel
            if len(cols_end) > 8:
                intel_desc = ' | '.join(cols_end[8:]).strip() or None

        results.append({
            'norad_id': norad,
            'name': name_raw,
            'designation': designation,
            'orbit_type': orbit_type,
            'operator': operator,
            'country': country,
            'status': status,
            'maneuverable': maneuverable,
            'users': users,
            'mission': mission,
            'launch_date': launch_date,
            'propulsion_type': propulsion_type,
            'propulsion_status': propulsion_status,
            'intel_description': intel_desc,
        })
    return results


def _create_pair_proposals(pair_rows: list[dict], source_title: str, source_id: str) -> list[dict]:
    """Turn parsed PAIR rows into KG attribute_update pending proposals for existing nodes."""
    from modules.knowledge_graph.kg_store import kg_store as _kg
    from api.routes_kg import _load_pending

    FIELD_MAP = {
        'status': 'status',
        'maneuverable': 'maneuverable',
        'propulsion_type': 'propulsion_type',
        'intel_description': 'intel_description',
        'designation': 'designation',
        'launch_date': 'launch_date',
        'operator': 'operator',
        'country': 'operator_country',
        'mission': 'mission',
        'orbit_type': 'orbit_type',
    }

    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()

    # Build set of (entity_id, field) pairs that already have a pending proposal
    existing_pending = _load_pending()
    already_pending: set[tuple[str, str]] = {
        (p.get('entity_id', ''), p.get('field', ''))
        for p in existing_pending.get('pending', [])
        if p.get('type') == 'attribute_update' and p.get('status') == 'pending'
    }

    proposals = []
    for row in pair_rows:
        norad = row.get('norad_id', '')
        node = _kg.nodes.get(norad)
        if not node:
            continue

        existing_attrs = node.get('attributes') or {}
        evidence = {
            'excerpt': f"PAIR row for NORAD {norad}: {row.get('name','')}",
            'source': {'source_id': source_id, 'title': source_title},
        }

        for pair_key, attr_name in FIELD_MAP.items():
            new_val = row.get(pair_key)
            if not new_val or str(new_val).strip() in ('', 'Unknown', 'None'):
                continue

            # Skip if field already set in KG
            existing = existing_attrs.get(attr_name)
            old_val = existing.get('value') if isinstance(existing, dict) else existing
            if old_val and str(old_val).strip():
                continue

            # Skip if already pending (prevents duplicates from multiple reprocessings)
            if (norad, attr_name) in already_pending:
                continue

            proposals.append({
                'id': f'pair_{uuid.uuid4().hex[:8]}',
                'type': 'attribute_update',
                'status': 'pending',
                'entity_id': norad,
                'field': attr_name,
                'old_value': old_val,
                'new_value': str(new_val).strip(),
                'evidence': evidence,
                'llm_assessment': f'Extracted from PAIR section (deterministic parser). Source: {source_title}',
                'created_at': now_str,
            })
            # Track within this run so two rows for same node don't both propose the same field
            already_pending.add((norad, attr_name))

    return proposals




@router.get("")
def get_all_events(
    type: str | None = Query(None),
    regime: str | None = Query(None, description="LEO | MEO | GEO | HEO"),
    days: int | None = Query(None, ge=1, description="Limit to events in the past N days"),
    satellite_id: str | None = Query(None),
):
    if regime or days or satellite_id:
        return event_store.query_events(event_type=type, regime=regime, days=days, satellite_id=satellite_id)
    return event_store.get_all(event_type=type)


@router.get("/satellite/{satellite_id}")
def get_satellite_events(satellite_id: str):
    return event_store.get_by_satellite(satellite_id)


@router.post("/extract/{source_id}")
async def extract_events(source_id: str):
    """Re-extract events from an already-stored source document."""
    doc = source_store._load_index().get(source_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    doc_file_rel = doc.get("file", "")
    text_path = SOURCES_DIR / doc_file_rel
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="Source text not found")

    raw = text_path.read_text(encoding="utf-8")
    # If stored as JSON dict (e.g. news articles), extract text field
    try:
        import json as _json
        parsed = _json.loads(raw)
        text = parsed.get("text") or parsed.get("content") or raw
    except Exception:
        text = raw
    events = await extract_events_from_jco(text, doc)
    added = []
    for ev in events:
        ev["source_id"] = source_id
        ev.setdefault("report_title", doc.get("title", ""))
        eid = event_store.add_event(ev)
        added.append(eid)
    return {"extracted": len(added), "event_ids": added}


@router.post("/notam/ingest")
async def ingest_notam_text(body: dict):
    """Parse raw ICAO NOTAM text, extract launch events, and store them."""
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text field required")

    # Collect already-known NOTAM IDs for dedup
    existing_notam_ids: set[str] = set()
    for ev in event_store.get_all(event_type="launch"):
        existing_notam_ids.update(ev.get("notam_ids") or [])

    events = await extract_launch_events(text, {})
    created = []
    for ev in events:
        new_ids = set(ev.get("notam_ids") or [])
        if new_ids and new_ids.issubset(existing_notam_ids):
            continue  # all IDs already stored — skip duplicate
        ids_str = ", ".join(sorted(new_ids)) if new_ids else "unknown"
        ev.setdefault("report_title", f"NOTAM {ids_str}")
        eid = event_store.add_event(ev)
        ev["id"] = eid
        created.append(ev)

    return {"count": len(created), "events": created}


@router.get("/notam")
def get_notam_events():
    """Return all stored launch events (NOTAM-sourced)."""
    return event_store.get_all(event_type="launch")


@router.get("/jco/unprocessed")
def get_unprocessed_jco():
    """Return .mhtml files in data/JCO report/ not yet in event store or source index."""
    if not JCO_DIR.exists():
        return {"unprocessed": [], "total_files": 0}

    all_files = sorted(JCO_DIR.glob("*.mhtml"), key=lambda f: f.name)

    # Filenames already present in event store
    processed: set[str] = set()
    for ev in event_store.get_all():
        rt = ev.get("report_title", "")
        if rt:
            processed.add(rt)

    # Filenames already ingested into source index
    for v in source_store._load_index().values():
        t = v.get("title", "")
        if t:
            processed.add(t)

    # Files that have KG source entries (processed through KG pipeline)
    from modules.knowledge_graph.kg_store import kg_store as _kg_store
    kg_processed_ids: set[str] = _kg_store.processed_sources

    unprocessed = []
    needs_kg = []
    for f in all_files:
        in_events = f.name in processed
        source_id = "file_" + hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        in_kg = source_id in kg_processed_ids
        if not in_events and not in_kg:
            unprocessed.append({"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1)})
        elif in_events and not in_kg:
            needs_kg.append({"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1)})

    return {"unprocessed": unprocessed, "needs_kg": needs_kg, "total_files": len(all_files)}


@router.post("/jco/process")
async def process_jco_files(body: dict):
    """Extract events AND KG entities from selected JCO report .mhtml files."""
    # Lazy import to avoid circular dependency at module load time
    from api.routes_kg import _run_ingest

    filenames: list[str] = body.get("files", [])
    if not filenames:
        raise HTTPException(status_code=400, detail="files list required")

    results = []
    for filename in filenames:
        path = JCO_DIR / filename
        if not path.exists():
            results.append({"file": filename, "status": "not_found", "events": 0, "kg_proposals": 0})
            continue
        try:
            raw_bytes = path.read_bytes()
            text = read_mhtml(path)
            if not text.strip():
                results.append({"file": filename, "status": "empty", "events": 0, "kg_proposals": 0})
                continue

            # Annotate multi-update sections so LLM knows latest takes precedence
            annotated_text = _annotate_jco_sections(text)

            # 1. Extract satellite events → event store
            events = await extract_events_from_jco(annotated_text, {"title": filename})
            added = []
            updated = []
            event_updates = []
            for ev in events:
                ev["report_title"] = filename
                result = event_store.add_event(ev)
                event_id = result["event_id"]

                if result["created"]:
                    added.append(event_id)
                elif result["updated"] and result["update_info"]:
                    updated.append(event_id)
                    event_updates.append({
                        "event_id": event_id,
                        "satellite_label": ev.get("satellite_label"),
                        "type": ev.get("type"),
                        "changes": result["update_info"]["changes"],
                        "summary": result["update_info"]["summary"],
                        "is_significant": result["update_info"]["is_significant"]
                    })

            # 2. Extract KG entities/relations → pending review queue
            source_id = "file_" + hashlib.sha256(raw_bytes).hexdigest()[:16]
            source = {"type": "report", "title": filename, "url": "", "date": ""}
            kg_result = await _run_ingest(annotated_text, source, source_id, mode="review")
            kg_proposals = kg_result.get("proposed", 0)

            # 3. Deterministic PAIR section parser — fills schema fields the LLM misses
            pair_rows = _parse_pair_rows(text)
            if pair_rows:
                pair_proposals = _create_pair_proposals(pair_rows, filename, source_id)
                if pair_proposals:
                    _append_pending_proposals(pair_proposals)
                    kg_proposals += len(pair_proposals)

            results.append({
                "file": filename,
                "status": "ok",
                "events_created": len(added),
                "events_updated": len(updated),
                "event_updates": event_updates,
                "kg_proposals": kg_proposals,
            })
        except Exception as exc:
            results.append({"file": filename, "status": "error", "error": str(exc), "events": 0, "kg_proposals": 0})

    return {"results": results}


@router.post("/jco/process-kg")
async def process_jco_kg_only(body: dict):
    """Run KG extraction only (no event extraction) for files already in the event store."""
    from api.routes_kg import _run_ingest

    filenames: list[str] = body.get("files", [])
    if not filenames:
        raise HTTPException(status_code=400, detail="files list required")

    results = []
    for filename in filenames:
        path = JCO_DIR / filename
        if not path.exists():
            results.append({"file": filename, "status": "not_found", "kg_proposals": 0})
            continue
        try:
            raw_bytes = path.read_bytes()
            text = read_mhtml(path)
            if not text.strip():
                results.append({"file": filename, "status": "empty", "kg_proposals": 0})
                continue
            source_id = "file_" + hashlib.sha256(raw_bytes).hexdigest()[:16]
            source = {"type": "report", "title": filename, "url": "", "date": ""}
            kg_result = await _run_ingest(text, source, source_id, mode="review")
            results.append({
                "file": filename,
                "status": "ok",
                "kg_proposals": kg_result.get("proposed", 0),
            })
        except Exception as exc:
            results.append({"file": filename, "status": "error", "error": str(exc), "kg_proposals": 0})

    return {"results": results}


@router.get("/jco/sources")
def get_jco_sources():
    """List all ingested JCO report files with event and KG proposal counts."""
    index = source_store._load_index()
    file_sources = {
        k: v for k, v in index.items()
        if k.startswith("file_") and v.get("type") == "report"
    }

    # Events grouped by source_id and by report_title
    events_by_source: dict[str, list] = {}
    events_by_title: dict[str, list] = {}
    for eid, ev in event_store.events.items():
        sid = ev.get("source_id", "")
        if sid:
            events_by_source.setdefault(sid, []).append({**ev, "id": eid})
        rt = ev.get("report_title", "")
        if rt:
            events_by_title.setdefault(rt, []).append({**ev, "id": eid})

    # Pending KG proposals grouped by source title
    pending_items = _load_pending_items()
    proposals_by_title: dict[str, int] = {}
    for p in pending_items:
        src = (p.get("evidence") or {}).get("source") or {}
        title = src.get("title", "") or src.get("source_id", "")
        if title:
            proposals_by_title[title] = proposals_by_title.get(title, 0) + 1

    result = []
    for source_id, meta in file_sources.items():
        title = meta.get("title", "")
        evs = events_by_source.get(source_id, []) or events_by_title.get(title, [])
        result.append({
            "source_id": source_id,
            "title": title,
            "ingested_at": meta.get("ingested_at", ""),
            "event_count": len(evs),
            "proposal_count": proposals_by_title.get(title, 0),
            "has_file": (JCO_DIR / title).exists() if title else False,
        })

    result.sort(key=lambda x: x["ingested_at"], reverse=True)
    return {"sources": result}


@router.get("/jco/source/{source_id}")
def get_jco_source_detail(source_id: str):
    """Return events and pending KG proposals for a specific JCO report."""
    index = source_store._load_index()
    meta = index.get(source_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Source not found")

    title = meta.get("title", "")

    # Collect all events for this source (match by source_id or report_title)
    events = []
    seen_ids: set[str] = set()
    for eid, ev in event_store.events.items():
        if ev.get("source_id") == source_id or ev.get("report_title") == title:
            if eid not in seen_ids:
                events.append({**ev, "id": eid})
                seen_ids.add(eid)

    # Collect pending KG proposals for this source
    pending_items = _load_pending_items()
    proposals = []
    for p in pending_items:
        src = (p.get("evidence") or {}).get("source") or {}
        src_title = src.get("title", "") or src.get("source_id", "")
        if src_title == title or src.get("source_id") == source_id:
            proposals.append({
                "id": p.get("id"),
                "type": p.get("type"),
                "status": p.get("status"),
                "label": (p.get("proposed") or {}).get("label"),
                "entity_type": (p.get("proposed") or {}).get("type"),
                "excerpt": (p.get("evidence") or {}).get("excerpt", "")[:120],
            })

    return {
        "source_id": source_id,
        "title": title,
        "ingested_at": meta.get("ingested_at", ""),
        "events": sorted(events, key=lambda e: e.get("event_date", ""), reverse=True),
        "proposals": proposals,
    }


@router.post("/jco/reprocess/{source_id}")
async def reprocess_jco_source(source_id: str):
    """Re-extract events and KG entities from a JCO report, replacing old events."""
    from api.routes_kg import _run_ingest

    index = source_store._load_index()
    meta = index.get(source_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Source not found")

    title = meta.get("title", "")
    path = JCO_DIR / title
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found on disk: {title}")

    # Delete existing events from this source before re-extracting
    to_delete = [
        eid for eid, ev in event_store.events.items()
        if ev.get("source_id") == source_id or ev.get("report_title") == title
    ]
    for eid in to_delete:
        event_store.delete(eid)

    raw_bytes = path.read_bytes()
    text = read_mhtml(path)
    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from file")

    # Annotate multi-update sections so LLM knows latest takes precedence
    annotated_text = _annotate_jco_sections(text)

    # Re-extract events
    events = await extract_events_from_jco(annotated_text, {"title": title})
    added_events = []
    for ev in events:
        ev["source_id"] = source_id
        ev["report_title"] = title
        eid = event_store.add_event(ev)
        added_events.append(eid)

    # Re-run KG extraction (force=True overwrites previous KG processing)
    kg_result = await _run_ingest(annotated_text, {"type": "report", "title": title, "url": "", "date": ""}, source_id, mode="review", force=True)
    kg_count = kg_result.get("proposed", 0)

    # Deterministic PAIR parser — catches fields the LLM misses
    pair_rows = _parse_pair_rows(text)
    if pair_rows:
        pair_proposals = _create_pair_proposals(pair_rows, title, source_id)
        if pair_proposals:
            _append_pending_proposals(pair_proposals)
            kg_count += len(pair_proposals)

    return {
        "source_id": source_id,
        "title": title,
        "deleted_events": len(to_delete),
        "new_events": len(added_events),
        "kg_proposals": kg_count,
    }


@router.delete("/{event_id}")
def delete_event(event_id: str):
    if event_store.delete(event_id):
        return {"deleted": event_id}
    raise HTTPException(status_code=404, detail="Event not found")


@router.get("/{event_id}/updates")
def get_event_updates(event_id: str, limit: int = Query(10, ge=1, le=100)):
    """Get update history for an event (when it was updated with new report versions).

    Returns:
    {
        "event_id": str,
        "satellite_label": str,
        "type": str,
        "created_at": str,
        "total_updates": int,
        "updates": [
            {
                "timestamp": str,
                "changes": [{field, old, new, type}],
                "summary": str
            }
        ]
    }
    """
    event = event_store.events.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    history = event.get("update_history", [])[-limit:]
    return {
        "event_id": event_id,
        "satellite_label": event.get("satellite_label"),
        "type": event.get("type"),
        "created_at": event.get("created_at"),
        "total_updates": len(event.get("update_history", [])),
        "updates": history
    }
