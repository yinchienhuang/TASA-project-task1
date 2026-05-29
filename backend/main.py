"""
TASA Backend — FastAPI entrypoint.
Start with: uvicorn main:app --reload  (from backend/)
"""
from dotenv import load_dotenv
load_dotenv()

import json as _json
import urllib.request
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_propagation import router as prop_router
from api.routes_analysis import router as analysis_router

_TLE_API = "https://tle.ivanstanojevic.me/api/tle"
_CELESTRAK_TLE = "https://celestrak.org/satcat/tle.php"  # fallback: ?CATNR=<norad_id>
from api.routes_ingestion import router as news_router
from api.routes_kg import router as kg_router
from api.routes_wiki import router as wiki_router
from api.routes_events import router as events_router
from modules.propagation import sgp4_propagator, tle_store
from modules.propagation.tle_history import snapshot as _tle_snapshot
from modules.ingestion import news_collector
from modules.knowledge_graph.schema import schema_manager
from modules.knowledge_graph.kg_store import kg_store
from modules.knowledge_graph.reference_lookup import reference_lookup


def _fetch_tle(norad_id: str, label: str):
    """Try primary TLE API, fall back to CelesTrak. Returns SatelliteMeta or None."""
    # Primary: tle.ivanstanojevic.me
    try:
        req = urllib.request.Request(
            f"{_TLE_API}/{norad_id}", headers={"User-Agent": "TASA/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            m = _json.loads(r.read())
        if m.get("line1") and m.get("line2"):
            return tle_store.upsert(norad_id, m["name"], m["line1"], m["line2"])
    except Exception:
        pass

    # Fallback: CelesTrak (returns raw 3-line TLE text)
    try:
        req = urllib.request.Request(
            f"{_CELESTRAK_TLE}?CATNR={norad_id}", headers={"User-Agent": "TASA/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
            name, line1, line2 = lines[0], lines[1], lines[2]
            return tle_store.upsert(norad_id, name, line1, line2)
        elif len(lines) == 2 and lines[0].startswith("1 ") and lines[1].startswith("2 "):
            return tle_store.upsert(norad_id, label, lines[0], lines[1])
    except Exception:
        pass

    print(f"[startup] no TLE available for {norad_id} ({label}) from any source")
    return None


def _sync_tle_from_kg() -> list[str]:
    """Ensure every KG satellite node with a numeric norad_id is in the TLE store.

    For satellites already seeded, we leave the seed as-is (fresh data comes from
    the ⟳ Refresh TLEs button or the scheduled job).  For satellites only in the KG
    (manually added, ingested, etc.) we fetch a current TLE from the public API so
    propagation works immediately.
    """
    fetched: list[str] = []
    for node in kg_store.nodes.values():
        all_types = [node.get("type", "")] + (node.get("inferred_types") or [])
        is_satellite = any(
            t == "Satellite" or (isinstance(t, str) and t.endswith("Satellite"))
            for t in all_types
        )
        if not is_satellite:
            continue
        raw = (node.get("attributes") or {}).get("norad_id") or {}
        norad_id = str(raw.get("value", "") or "").strip()
        if not norad_id or not norad_id.isdigit():
            continue
        if tle_store.get(norad_id):
            continue  # already seeded — leave as-is
        label = node.get("label", norad_id)
        sat = _fetch_tle(norad_id, label)
        if sat:
            fetched.append(f"{norad_id} ({sat.name})")
    return fetched

app = FastAPI(title="TASA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prop_router)
app.include_router(news_router)
app.include_router(kg_router)
app.include_router(wiki_router)
app.include_router(events_router)
app.include_router(analysis_router)

_position_cache: dict[str, list[dict]] = {}
_scheduler = BackgroundScheduler()


@app.on_event("startup")
async def startup():
    import pathlib

    # 1. Load KG (source of truth for which satellites exist)
    schema_path = pathlib.Path(__file__).parent.parent / "data" / "schema" / "schema.yaml"
    schema_manager.load(schema_path)
    kg_store.load()
    reference_lookup.load()

    # 2. Sync TLE store from KG — fetch TLEs for any KG satellite not already seeded
    fetched = _sync_tle_from_kg()
    if fetched:
        print(f"[startup] fetched TLEs for KG satellites: {fetched}")

    # 3. Pre-compute positions only for satellites present in the KG
    kg_norad_ids: set[str] = set()
    for node in kg_store.nodes.values():
        raw = (node.get("attributes") or {}).get("norad_id") or {}
        norad_id = str(raw.get("value", "") or "").strip()
        if norad_id and norad_id.isdigit():
            kg_norad_ids.add(norad_id)

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(hours=12)
    end = now + timedelta(hours=12)
    no_tle = []
    for norad_id in kg_norad_ids:
        sat = tle_store.get(norad_id)
        if not sat:
            no_tle.append(norad_id)
            continue
        positions = sgp4_propagator.get_positions(sat.line1, sat.line2, start, end, step_seconds=60)
        _position_cache[sat.norad_id] = [
            {"lat": p.lat, "lon": p.lon, "alt": p.alt, "timestamp": p.timestamp}
            for p in positions
        ]
    print(f"[startup] pre-computed positions for {list(_position_cache.keys())}")
    if no_tle:
        print(f"[startup] skipped (no TLE available): {no_tle}")

    # 4. Snapshot current TLEs into history archive (runs once at startup, then daily)
    def _snapshot_all_tles():
        count = 0
        for sat in tle_store.all_satellites():
            if sat.line1 and sat.line2:
                _tle_snapshot(sat.norad_id, sat.line1, sat.line2)
                count += 1
        print(f"[tle_history] snapshotted {count} TLEs")

    _scheduler.add_job(
        _snapshot_all_tles,
        "interval", hours=24, id="tle_history_snapshot",
        next_run_time=datetime.now(timezone.utc),
    )

    # 5. Schedule news refresh every 6 hours (first run on user request only)
    _scheduler.add_job(news_collector.collect_all, "interval", hours=6)
    _scheduler.start()
    print("[startup] news scheduler started (first fetch on user request)")


@app.on_event("shutdown")
async def shutdown():
    _scheduler.shutdown(wait=False)


@app.get("/api/propagation/positions/cached/{norad_id}")
def get_cached_positions(norad_id: str):
    data = _position_cache.get(norad_id)
    if data is None:
        return {"error": "not cached", "positions": []}
    return {"positions": data}


@app.get("/")
def root():
    return {"status": "ok", "service": "TASA API"}
