from datetime import datetime, timezone
from typing import Optional
import urllib.request
import json as _json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from modules.propagation import sgp4_propagator, proximity as prox, tle_store
from modules.propagation.tle_history import snapshot as _tle_snapshot

_TLE_API = "https://tle.ivanstanojevic.me/api/tle"
_CELESTRAK_TLE = "https://celestrak.org/satcat/tle.php"

router = APIRouter(prefix="/api/propagation", tags=["propagation"])


class TLEIn(BaseModel):
    norad_id: str
    name: str
    line1: str
    line2: str


def _parse_dt(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid datetime: {s}")


def _fetch_and_cache_tle(norad_id: str) -> None:
    """Fetch TLE from external API and store it in tle_store. No-op on failure."""
    try:
        req = urllib.request.Request(f"{_TLE_API}/{norad_id}", headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            m = _json.loads(r.read())
        if m.get("line1") and m.get("line2"):
            tle_store.upsert(norad_id, m["name"], m["line1"], m["line2"])
            _tle_snapshot(norad_id, m["line1"], m["line2"])
            return
    except Exception:
        pass
    try:
        req = urllib.request.Request(f"{_CELESTRAK_TLE}?CATNR={norad_id}", headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
            tle_store.upsert(norad_id, lines[0], lines[1], lines[2])
            _tle_snapshot(norad_id, lines[1], lines[2])
        elif len(lines) == 2 and lines[0].startswith("1 ") and lines[1].startswith("2 "):
            tle_store.upsert(norad_id, norad_id, lines[0], lines[1])
            _tle_snapshot(norad_id, lines[0], lines[1])
    except Exception:
        pass


@router.get("/tle/search")
def search_tle(name: str = Query(..., min_length=2)):
    """Search tle.ivanstanojevic.me by satellite name; returns up to 20 matches."""
    try:
        url = f"{_TLE_API}/?search={urllib.request.quote(name)}&page-size=20"
        req = urllib.request.Request(url, headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read())
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"TLE lookup failed: {e}")
    members = data.get("member", [])
    return [
        {
            "noradId": str(m["satelliteId"]),
            "name": m["name"],
            "line1": m.get("line1", ""),
            "line2": m.get("line2", ""),
        }
        for m in members
        if m.get("line1") and m.get("line2")
    ]


@router.get("/tle/{norad_id}")
def fetch_tle(norad_id: str):
    """Fetch TLE for a NORAD ID — tries primary API then CelesTrak fallback."""
    # Primary
    try:
        req = urllib.request.Request(f"{_TLE_API}/{norad_id}", headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            m = _json.loads(r.read())
        if m.get("line1") and m.get("line2"):
            return {"noradId": str(m["satelliteId"]), "name": m["name"], "line1": m["line1"], "line2": m["line2"]}
    except Exception:
        pass

    # Fallback: CelesTrak
    try:
        req = urllib.request.Request(f"{_CELESTRAK_TLE}?CATNR={norad_id}", headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
            return {"noradId": norad_id, "name": lines[0], "line1": lines[1], "line2": lines[2]}
        if len(lines) == 2 and lines[0].startswith("1 ") and lines[1].startswith("2 "):
            return {"noradId": norad_id, "name": norad_id, "line1": lines[0], "line2": lines[1]}
    except Exception:
        pass

    raise HTTPException(status_code=404, detail=f"TLE not found for NORAD ID {norad_id}")


@router.get("/satellites")
def list_satellites():
    return [
        {"norad_id": s.norad_id, "name": s.name}
        for s in tle_store.all_satellites()
    ]


@router.post("/tle")
def upsert_tle(body: TLEIn):
    meta = tle_store.upsert(body.norad_id, body.name, body.line1, body.line2)
    _tle_snapshot(body.norad_id, body.line1, body.line2)
    return {"norad_id": meta.norad_id, "name": meta.name}


@router.post("/tle/refresh-all")
def refresh_all_tles():
    """Fetch fresh TLEs from tle.ivanstanojevic.me for every tracked satellite."""
    results = []
    for sat in tle_store.all_satellites():
        try:
            url = f"{_TLE_API}/{sat.norad_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "TASA/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                m = _json.loads(r.read())
            if m.get("line1") and m.get("line2"):
                tle_store.upsert(sat.norad_id, m["name"], m["line1"], m["line2"])
                _tle_snapshot(sat.norad_id, m["line1"], m["line2"])
                results.append({"norad_id": sat.norad_id, "name": m["name"], "status": "updated"})
            else:
                results.append({"norad_id": sat.norad_id, "name": sat.name, "status": "no_data"})
        except Exception as e:
            results.append({"norad_id": sat.norad_id, "name": sat.name, "status": "error", "detail": str(e)})
    return {"results": results}


@router.get("/position/{norad_id}")
def get_position(
    norad_id: str,
    time: Optional[str] = Query(None, description="ISO 8601 datetime; defaults to now"),
):
    meta = tle_store.get(norad_id)
    if not meta:
        _fetch_and_cache_tle(norad_id)
        meta = tle_store.get(norad_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Satellite not found")
    dt = _parse_dt(time) if time else datetime.now(timezone.utc)
    pos = sgp4_propagator.get_position(meta.line1, meta.line2, dt)
    if pos is None:
        raise HTTPException(status_code=500, detail="SGP4 propagation error")
    return {"lat": pos.lat, "lon": pos.lon, "alt": pos.alt, "timestamp": pos.timestamp}


@router.get("/positions/{norad_id}")
def get_positions(
    norad_id: str,
    start: str = Query(...),
    end: str = Query(...),
    step: int = Query(60, ge=1, le=3600),
):
    meta = tle_store.get(norad_id)
    if not meta:
        _fetch_and_cache_tle(norad_id)
        meta = tle_store.get(norad_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Satellite not found")
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    if end_dt <= start_dt:
        raise HTTPException(status_code=422, detail="end must be after start")
    positions = sgp4_propagator.get_positions(meta.line1, meta.line2, start_dt, end_dt, step)
    return [{"lat": p.lat, "lon": p.lon, "alt": p.alt, "timestamp": p.timestamp} for p in positions]


@router.get("/proximity")
def get_proximity(
    sat1: str = Query(...),
    sat2: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    step: int = Query(60, ge=1, le=3600),
):
    m1 = tle_store.get(sat1)
    m2 = tle_store.get(sat2)
    if not m1:
        raise HTTPException(status_code=404, detail=f"Satellite {sat1} not found")
    if not m2:
        raise HTTPException(status_code=404, detail=f"Satellite {sat2} not found")
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    result = prox.min_distance(m1.line1, m1.line2, m2.line1, m2.line2, start_dt, end_dt, step)
    if result is None:
        raise HTTPException(status_code=500, detail="No valid positions computed")
    return {
        "min_distance_km": result.min_distance_km,
        "at_time": result.at_time,
        "sat1_pos": result.sat1_pos,
        "sat2_pos": result.sat2_pos,
    }
