"""
Analysis API routes: coverage analysis and natural language Q&A.
"""
import asyncio
from functools import lru_cache
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from modules.analysis.coverage import compute_passes, passes_summary, REGIONS
from modules.analysis.satellite_utils import _is_chinese_satellite, _is_satellite_node
from modules.propagation import tle_store
from modules.knowledge_graph.kg_store import kg_store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# Simple 1-entry LRU cache keyed by (norad_id, region, days) — invalidated on restart
_coverage_cache: dict[tuple, dict] = {}


@router.get("/regions")
def list_regions():
    """List available named regions for coverage analysis."""
    return [
        {"id": k, "label": k.replace("_", " ").title(), "bounds": v}
        for k, v in REGIONS.items()
    ]


@router.get("/coverage/{norad_id}")
def get_single_coverage(
    norad_id: str,
    region: str = Query("taiwan", description="Named region ID or 'custom'"),
    days: int = Query(7, ge=1, le=90),
):
    """Compute pass statistics for one satellite over a named region."""
    cache_key = (norad_id, region, days)
    if cache_key in _coverage_cache:
        return _coverage_cache[cache_key]

    region_bounds = REGIONS.get(region)
    if not region_bounds:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region}'. Available: {list(REGIONS)}")

    sat = tle_store.get(norad_id)
    if not sat:
        raise HTTPException(status_code=404, detail=f"No TLE for NORAD ID {norad_id}")

    passes = compute_passes(sat.line1, sat.line2, region_bounds, days=days)
    summary = passes_summary(passes, days)

    result = {"norad_id": norad_id, "region": region, "days": days, "passes": passes, "summary": summary}
    _coverage_cache[cache_key] = result
    return result


@router.get("/coverage/fleet/search")
def get_fleet_coverage(
    country: str = Query("china"),
    region: str = Query("taiwan"),
    days: int = Query(30, ge=1, le=90),
):
    """Rank satellites from a given country by passes over a region."""
    cache_key = (f"fleet_{country}", region, days)
    if cache_key in _coverage_cache:
        return _coverage_cache[cache_key]

    region_bounds = REGIONS.get(region)
    if not region_bounds:
        raise HTTPException(status_code=404, detail=f"Unknown region '{region}'")

    # Collect candidate satellites
    candidates = []
    for node in kg_store.nodes.values():
        if not _is_satellite_node(node):
            continue
        if country.lower() in ("china", "chinese") and not _is_chinese_satellite(node):
            continue
        attrs = node.get("attributes") or {}
        norad_id = str((attrs.get("norad_id") or {}).get("value") or "").strip()
        if not norad_id or not norad_id.isdigit():
            continue
        sat = tle_store.get(norad_id)
        if not sat:
            continue
        candidates.append((node, sat))

    results = []
    for node, sat in candidates:
        try:
            passes = compute_passes(sat.line1, sat.line2, region_bounds, days=days)
            summary = passes_summary(passes, days)
            results.append({
                "norad_id": sat.norad_id,
                "label": node.get("label", sat.norad_id),
                "node_id": node.get("id", ""),
                "summary": summary,
            })
        except Exception as e:
            print(f"[coverage] error for {sat.norad_id}: {e}")

    results.sort(key=lambda r: r["summary"]["avg_passes_per_day"], reverse=True)
    result = {"country": country, "region": region, "days": days, "satellites": results}
    _coverage_cache[cache_key] = result
    return result


# ── Q&A endpoint ──────────────────────────────────────────────────────────────

class HistoryMessage(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class QueryRequest(BaseModel):
    question: str
    satellite_id: str | None = None
    history: list[HistoryMessage] | None = None  # Multi-turn conversation history


@router.post("/query")
async def run_query(req: QueryRequest):
    """Run a natural language Q&A over satellite data using GPT-4o tool calling.

    Supports multi-turn conversation with context from previous exchanges.
    """
    from modules.analysis.qa_engine import run_qa
    result = await run_qa(
        req.question,
        satellite_id=req.satellite_id,
        history=req.history or []
    )
    return result


@router.get("/conjunction/nearby")
def get_conjunctions_nearby(
    norad_id: str = Query(..., description="NORAD catalog number"),
    days: int = Query(30, ge=1, le=90),
    min_distance_km: float = Query(100.0, ge=1),
):
    """Get conjunction warnings for a satellite.

    Uses cached Space-Track CDM data (refreshed on-demand if > 8 hours old).
    Respects API limits: 3 CDM queries per day (1 every 8 hours).
    """
    from modules.analysis.spacetrack_client import get_spacetrack_client
    from modules.analysis.conjunction_cache import conjunction_cache

    # Check if cache needs refresh
    from_cache = not conjunction_cache.needs_refresh()

    if conjunction_cache.needs_refresh():
        # Fetch fresh CDM data from Space-Track
        client = get_spacetrack_client()
        all_cdms = client.get_conjunctions(
            norad_id=None,  # None = fetch ALL CDMs (not filtered by satellite)
            days_ahead=30,
            min_distance_km=0  # No distance filter on fetch; filter client-side
        )
        if all_cdms is not None:
            conjunction_cache.update(all_cdms)
            from_cache = False
        else:
            # Fall back to stale cache if API fails
            from_cache = True

    # Query from cache
    conjunctions = conjunction_cache.get_conjunctions_for_satellite(
        norad_id, days=days, min_distance_km=min_distance_km
    )

    return {
        "norad_id": norad_id,
        "days": days,
        "min_distance_km": min_distance_km,
        "count": len(conjunctions),
        "conjunctions": conjunctions,
        "source": "space-track.org (cached)",
        "from_cache": from_cache,
        "cache_age_hours": round(
            (datetime.now(timezone.utc) -
             datetime.fromisoformat(conjunction_cache.last_updated() or "1970-01-01T00:00:00+00:00")
            ).total_seconds() / 3600, 1
        ) if conjunction_cache.last_updated() else None,
    }


@router.get("/conjunction/cache-status")
def get_conjunction_cache_status():
    """Get CDM cache status and last update time."""
    from modules.analysis.conjunction_cache import conjunction_cache

    last_updated = conjunction_cache.last_updated()
    needs_refresh = conjunction_cache.needs_refresh()

    if last_updated:
        try:
            last_dt = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)
            age_hours = round((datetime.now(timezone.utc) - last_dt).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            age_hours = None
    else:
        age_hours = None

    return {
        "last_updated": last_updated,
        "age_hours": age_hours,
        "needs_refresh": needs_refresh,
        "refresh_interval_hours": 8,
    }


@router.get("/conjunction/satellites")
def get_all_satellites_with_norad():
    """Get all satellites in KG that have NORAD IDs (for conjunction querying)."""
    sats = []
    for node in kg_store.nodes.values():
        if not _is_satellite_node(node):
            continue

        attrs = node.get("attributes") or {}
        norad_id = str((attrs.get("norad_id") or {}).get("value") or "").strip()
        if not norad_id or not norad_id.isdigit():
            continue

        sats.append({
            "norad_id": norad_id,
            "label": node.get("label", norad_id),
            "node_id": node.get("id", ""),
        })

    # Sort by label
    sats.sort(key=lambda x: x["label"])
    return {"satellites": sats, "count": len(sats)}


@router.get("/conjunction/system-satellites")
def get_system_satellites_conjunctions(
    days: int = Query(30, ge=1, le=90),
    min_distance_km: float = Query(100.0, ge=1),
):
    """Get conjunction warnings for all satellites in the KG system.

    Queries cache for conjunctions involving any KG satellite,
    then filters to only those with at least one satellite in the system.
    """
    from modules.analysis.conjunction_cache import conjunction_cache

    # Get all KG satellites NORAD IDs
    kg_sat_ids = set()
    for node in kg_store.nodes.values():
        if not _is_satellite_node(node):
            continue
        attrs = node.get("attributes") or {}
        norad_id = str((attrs.get("norad_id") or {}).get("value") or "").strip()
        if norad_id and norad_id.isdigit():
            kg_sat_ids.add(norad_id)

    # Refresh cache if needed
    if conjunction_cache.needs_refresh():
        from modules.analysis.spacetrack_client import get_spacetrack_client

        client = get_spacetrack_client()
        all_cdms = client.get_conjunctions(
            norad_id=None, days_ahead=days, min_distance_km=0
        )
        if all_cdms is not None:
            conjunction_cache.update(all_cdms)

    # Get all cached conjunctions
    conjunction_cache._load()
    cdms = conjunction_cache._data.get("cdms", [])

    # Filter by: at least one satellite in KG, distance, and date
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    past_cutoff = now - timedelta(days=days)
    future_cutoff = now + timedelta(days=days)

    results = []
    for cdm in cdms:
        # Only include if at least one satellite is in KG
        sat1_in_kg = str(cdm.get("norad_id_1", "")) in kg_sat_ids
        sat2_in_kg = str(cdm.get("norad_id_2", "")) in kg_sat_ids
        if not (sat1_in_kg or sat2_in_kg):
            continue

        # Filter by distance
        if float(cdm.get("min_distance_km", float("inf"))) > min_distance_km:
            continue

        # Filter by date
        try:
            tca = datetime.fromisoformat(cdm.get("tca", "").replace("Z", "+00:00"))
            if tca < past_cutoff or tca > future_cutoff:
                continue
        except (ValueError, TypeError):
            continue

        results.append(cdm)

    # Sort by TCA (newest first)
    results.sort(key=lambda x: x.get("tca", ""), reverse=True)

    return {
        "days": days,
        "min_distance_km": min_distance_km,
        "count": len(results),
        "conjunctions": results,
        "source": "space-track.org (cached)",
        "kg_satellites_count": len(kg_sat_ids),
    }


@router.get("/conjunction/all-satellites")
def get_all_conjunctions(
    days: int = Query(30, ge=1, le=90),
    min_distance_km: float = Query(100.0, ge=1),
):
    """Get conjunction warnings for ALL satellites in cache (no filtering).

    Returns all conjunction predictions from cached Space-Track data,
    sorted by time and risk level.
    """
    from modules.analysis.conjunction_cache import conjunction_cache

    # Return all cached conjunctions, filtered by distance and days only
    cache_loaded = False
    if conjunction_cache.needs_refresh():
        from modules.analysis.spacetrack_client import get_spacetrack_client
        client = get_spacetrack_client()
        all_cdms = client.get_conjunctions(
            norad_id=None, days_ahead=days, min_distance_km=0
        )
        if all_cdms is not None:
            conjunction_cache.update(all_cdms)
            cache_loaded = True

    # Get all cached conjunctions
    conjunction_cache._load()
    cdms = conjunction_cache._data.get("cdms", [])

    # Filter by distance and date
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    past_cutoff = now - timedelta(days=days)
    future_cutoff = now + timedelta(days=days)

    results = []
    for cdm in cdms:
        # Filter by distance
        if float(cdm.get("min_distance_km", float("inf"))) > min_distance_km:
            continue

        # Filter by date
        try:
            tca = datetime.fromisoformat(cdm.get("tca", "").replace("Z", "+00:00"))
            if tca < past_cutoff or tca > future_cutoff:
                continue
        except (ValueError, TypeError):
            continue

        results.append(cdm)

    # Sort by TCA (newest first)
    results.sort(key=lambda x: x.get("tca", ""), reverse=True)

    return {
        "days": days,
        "min_distance_km": min_distance_km,
        "count": len(results),
        "conjunctions": results,
        "source": "space-track.org (cached)",
        "from_cache": not cache_loaded,
    }


@router.get("/conjunction/taiwan-fleet")
def get_taiwan_satellite_conjunctions(
    days: int = Query(30, ge=1, le=90),
    min_distance_km: float = Query(100.0, ge=1),
):
    """Get conjunction warnings for all Taiwan-operated satellites in KG.

    Filters KG for Taiwan operators, fetches conjunctions from Space-Track.
    Returns aggregated results sorted by time and risk.
    """
    from modules.analysis.spacetrack_client import get_spacetrack_client

    # Find Taiwan satellites in KG
    taiwan_sats = []
    for node in kg_store.nodes.values():
        if not _is_satellite_node(node):
            continue
        if not _is_chinese_satellite(node):  # ← For now, using Chinese as proxy
            continue

        attrs = node.get("attributes") or {}
        norad_id = str((attrs.get("norad_id") or {}).get("value") or "").strip()
        if not norad_id or not norad_id.isdigit():
            continue

        taiwan_sats.append({
            "norad_id": norad_id,
            "label": node.get("label", norad_id),
            "node_id": node.get("id", ""),
        })

    if not taiwan_sats:
        return {
            "satellites": [],
            "conjunctions": [],
            "count": 0,
            "message": "No satellites found in KG",
        }

    # Fetch conjunctions for each satellite
    client = get_spacetrack_client()
    all_conjunctions = []

    for sat in taiwan_sats:
        conjunctions = client.get_conjunctions(
            sat["norad_id"],
            days_ahead=days,
            min_distance_km=min_distance_km,
        )

        if conjunctions:
            for conj in conjunctions:
                conj["primary_sat"] = sat["label"]
                conj["primary_norad"] = sat["norad_id"]
                conj["primary_node_id"] = sat["node_id"]
                all_conjunctions.append(conj)

    # Sort by TCA time
    all_conjunctions.sort(key=lambda x: x["tca"])

    return {
        "satellites": taiwan_sats,
        "days": days,
        "min_distance_km": min_distance_km,
        "count": len(all_conjunctions),
        "conjunctions": all_conjunctions[:50],  # Limit to 50 for UI performance
        "source": "space-track.org",
    }
