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

_SPACETRACK_TLE = "https://www.space-track.org/basicspacedata/query/class/tle_latest/NORAD_CAT_ID"
_TLE_API = "https://tle.ivanstanojevic.me/api/tle"
_CELESTRAK_TLE = "https://celestrak.org/satcat/tle.php"
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
    """Try TLE APIs in priority order. Returns SatelliteMeta or None."""
    # Primary: tle.ivanstanojevic.me (fast)
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

    # Secondary: CelesTrak
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

    # Tertiary: Space-Track (reliable but slower)
    try:
        import os
        username = os.environ.get("SPACETRACK_USERNAME")
        password = os.environ.get("SPACETRACK_PASSWORD")

        if username and password:
            import requests
            session = requests.Session()
            login_resp = session.post(
                "https://www.space-track.org/ajaxauth/login",
                data={"identity": username, "password": password},
                timeout=8
            )

            if login_resp.status_code == 200:
                tle_resp = session.get(
                    f"{_SPACETRACK_TLE}/{norad_id}/format/json",
                    timeout=8
                )
                if tle_resp.status_code == 200:
                    data = tle_resp.json()
                    if data and len(data) > 0:
                        rec = data[0]
                        line1 = rec.get("TLE_LINE1", "").strip()
                        line2 = rec.get("TLE_LINE2", "").strip()
                        if line1 and line2:
                            return tle_store.upsert(norad_id, label, line1, line2)
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
    import time

    t0 = time.time()

    # 1. Load KG (source of truth for which satellites exist)
    print("[startup] Loading KG...")
    schema_path = pathlib.Path(__file__).parent.parent / "data" / "schema" / "schema.yaml"
    schema_manager.load(schema_path)
    kg_store.load()
    reference_lookup.load()
    t1 = time.time()
    print(f"[startup] KG loaded in {t1-t0:.2f}s")

    # 1.4 Load TLE from files (data/tle/*.json)
    print("[startup] Loading TLE files...")
    tle_store.load_from_disk()
    t1_tle = time.time()
    tles_count = len(tle_store.all_satellites())
    print(f"[startup] Loaded {tles_count} TLEs from disk in {t1_tle-t1:.2f}s")

    # 1.5 Populate orbit_type (LEO/MEO/GEO/HEO) for satellites with orbital_period
    from modules.events.event_store import classify_regime
    updated = 0
    for node in kg_store.nodes.values():
        all_types = [node.get("type", "")] + (node.get("inferred_types") or [])
        is_satellite = any(
            t == "Satellite" or (isinstance(t, str) and t.endswith("Satellite"))
            for t in all_types
        )
        if not is_satellite:
            continue
        attrs = node.get("attributes") or {}

        # Skip if orbit_type already set
        if attrs.get("orbit_type", {}).get("value"):
            continue

        # Try to compute from orbital_period
        period_data = attrs.get("orbital_period") or {}
        period_val = period_data.get("value") if isinstance(period_data, dict) else period_data
        if not period_val:
            continue

        try:
            period_min = float(period_val)
            regime = classify_regime(period_min)
            if "attributes" not in node:
                node["attributes"] = {}
            node["attributes"]["orbit_type"] = {"value": regime, "source": "auto_from_orbital_period"}
            updated += 1
        except (ValueError, TypeError):
            pass

    if updated > 0:
        kg_store.save()
        print(f"[startup] orbit_type populated for {updated} satellites")

    # 1.6 Backfill regime field in existing events (from satellite's orbit_type or KG data)
    from modules.events.event_store import event_store
    event_updated = 0
    event_store._load()
    for event in event_store.events.values():
        if event.get("regime"):
            continue  # already has regime

        # Try to get regime from satellite's orbit_type in KG
        sat_id = event.get("satellite_id")
        if sat_id:
            for node in kg_store.nodes.values():
                node_attrs = node.get("attributes") or {}
                norad_id = str(node_attrs.get("norad_id", {}).get("value", "") or "").strip()
                if norad_id == sat_id:
                    orbit_type = node_attrs.get("orbit_type", {}).get("value")
                    if orbit_type:
                        event["regime"] = orbit_type
                        event_updated += 1
                    break
            # Try from orbital_period in event itself
            if not event.get("regime") and event.get("orbital_period"):
                try:
                    period_min = float(event.get("orbital_period"))
                    event["regime"] = classify_regime(period_min)
                    event_updated += 1
                except (ValueError, TypeError):
                    pass

    if event_updated > 0:
        event_store.save()
        print(f"[startup] regime backfilled for {event_updated} events")

    # 2. For satellites in KG but not in TLE files, fetch TLE (on-demand only)
    # We only fetch missing TLEs to avoid excessive API calls
    print("[startup] Checking for satellites in KG missing TLEs...")
    missing_tles = _sync_tle_from_kg()
    if missing_tles:
        print(f"[startup] Fetched TLEs for {len(missing_tles)} satellites: {', '.join(missing_tles[:5])}")
    else:
        print("[startup] All KG satellites have TLE data")

    # 3. Skip position pre-computation (TLEs loaded on-demand)
    print("[startup] Position caching: deferred to on-demand")
    t4 = time.time()
    print(f"[startup] TOTAL STARTUP TIME: {t4-t0:.2f}s")

    # 4. Snapshot current TLEs into history archive (runs once at startup, then daily)
    def _snapshot_all_tles():
        count = 0
        for sat in tle_store.all_satellites():
            if sat.line1 and sat.line2:
                _tle_snapshot(sat.norad_id, sat.line1, sat.line2)
                count += 1
        if count > 0:
            print(f"[tle_history] snapshotted {count} TLEs")
        else:
            print(f"[tle_history] no TLEs in store yet (will snapshot on-demand fetches)")

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
