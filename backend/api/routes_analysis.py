"""
Analysis API routes: coverage analysis and natural language Q&A.
"""
import asyncio
from functools import lru_cache
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from modules.analysis.coverage import compute_passes, passes_summary, REGIONS
from modules.propagation import tle_store
from modules.knowledge_graph.kg_store import kg_store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_CHINESE_OPERATORS = {"casc", "cnsa", "pla", "china", "chinese", "cast", "cgwic", "commsat"}


def _is_chinese_satellite(node: dict) -> bool:
    """Heuristic: check if a KG satellite node is operated by a Chinese entity."""
    attrs = node.get("attributes") or {}
    operator = str((attrs.get("operator") or {}).get("value") or "").lower()
    if any(kw in operator for kw in _CHINESE_OPERATORS):
        return True
    # Also check edges via kg_store
    nid = node.get("id", "")
    for eid, edge in kg_store.edges.items():
        if edge.get("source") == nid and edge.get("type") in ("operatedBy", "builtBy", "ownedBy"):
            target_id = edge.get("target", "")
            target_node = kg_store.nodes.get(target_id, {})
            target_label = (target_node.get("label") or "").lower()
            if any(kw in target_label for kw in _CHINESE_OPERATORS):
                return True
    return False


def _is_satellite_node(node: dict) -> bool:
    all_types = [node.get("type", "")] + (node.get("inferred_types") or [])
    return any(t == "Satellite" for t in all_types)


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

class QueryRequest(BaseModel):
    question: str
    satellite_id: str | None = None


@router.post("/query")
async def run_query(req: QueryRequest):
    """Run a natural language Q&A over satellite data using GPT-4o tool calling."""
    from modules.analysis.qa_engine import run_qa
    result = await run_qa(req.question, satellite_id=req.satellite_id)
    return result
