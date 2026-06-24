from datetime import datetime, timezone
from typing import Optional
import urllib.request
import json as _json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from modules.propagation import sgp4_propagator, proximity as prox, tle_store
from modules.propagation.tle_history import snapshot as _tle_snapshot
from modules.knowledge_graph.kg_store import kg_store
import os

_TLE_API = "https://tle.ivanstanojevic.me/api/tle"
_CELESTRAK_TLE = "https://celestrak.org/satcat/tle.php"
_SPACETRACK_TLE = "https://www.space-track.org/basicspacedata/query/class/tle_latest/NORAD_CAT_ID"

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
    """Search TLE by satellite name or NORAD ID. Tries multiple sources.

    - If input is a NORAD ID (digits only), uses fetch_tle directly (3 sources)
    - If input is a name, searches tle.ivanstanojevic.me then CelesTrak
    """
    results = []

    # Check if input is a NORAD ID (all digits)
    if name.strip().isdigit():
        norad_id = name.strip()
        # Direct NORAD ID lookup using fetch_tle (which has 3 TLE sources)
        try:
            result = fetch_tle(norad_id)
            return [result]
        except HTTPException:
            # TLE not found, try Space-Track SATCAT as fallback
            pass  # Fall through to Space-Track SATCAT search below

    # Name search: try tle.ivanstanojevic.me first
    try:
        url = f"{_TLE_API}/?search={urllib.request.quote(name)}&page-size=20"
        req = urllib.request.Request(url, headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read())
        members = data.get("member", [])
        results = [
            {
                "noradId": str(m["satelliteId"]),
                "name": m["name"],
                "line1": m.get("line1", ""),
                "line2": m.get("line2", ""),
            }
            for m in members
            if m.get("line1") and m.get("line2")
        ]
        if results:
            return results
    except Exception:
        pass

    # Fallback: Search CelesTrak
    try:
        url = f"{_CELESTRAK_TLE}?NORAD_CAT_ID=&INTLDES=&SATNAME=*{urllib.request.quote(name)}*"
        req = urllib.request.Request(url, headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        # Parse CelesTrak format (SATNAME, LINE1, LINE2 triplets)
        for i in range(0, len(lines) - 2, 3):
            if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
                # Extract NORAD ID from TLE line 1 (positions 2-7)
                norad_id = lines[i + 1][2:7].strip()
                results.append({
                    "noradId": norad_id,
                    "name": lines[i],
                    "line1": lines[i + 1],
                    "line2": lines[i + 2],
                })

        if results:
            return results
    except Exception:
        pass

    # Last resort: Query Space-Track SATCAT (even if no TLE available)
    try:
        username = os.environ.get("SPACETRACK_USERNAME")
        password = os.environ.get("SPACETRACK_PASSWORD")

        if username and password:
            import requests

            session = requests.Session()
            login_resp = session.post(
                "https://www.space-track.org/ajaxauth/login",
                data={"identity": username, "password": password},
                timeout=10,
            )

            if login_resp.status_code == 200:
                # Search SATCAT by NORAD ID or name
                if name.isdigit():
                    # Search by NORAD_CAT_ID
                    satcat_url = (
                        "https://www.space-track.org/basicspacedata/query/class/satcat"
                        f"/NORAD_CAT_ID/{name}/format/json"
                    )
                else:
                    # Search by SATNAME
                    satcat_url = (
                        "https://www.space-track.org/basicspacedata/query/class/satcat"
                        f"/SATNAME/*{urllib.request.quote(name)}*/orderby/SATNAME/format/json"
                    )
                satcat_resp = session.get(satcat_url, timeout=30)

                if satcat_resp.status_code == 200:
                    sats = satcat_resp.json()
                    for sat in sats:
                        norad_id = str(sat.get("NORAD_CAT_ID", "")).strip()
                        satname = sat.get("SATNAME", norad_id)

                        # Try to get TLE via gp class (correct Space-Track endpoint)
                        tle_result = None
                        try:
                            # Use gp class with latest TLE (ORDER BY EPOCH DESC LIMIT 1)
                            tle_url = f"https://www.space-track.org/basicspacedata/query/class/gp/NORAD_CAT_ID/{norad_id}/orderby/EPOCH%20desc/limit/1/format/tle"
                            tle_resp = session.get(tle_url, timeout=10)
                            if tle_resp.status_code == 200:
                                tle_text = tle_resp.text.strip()
                                # TLE format: line1, line2
                                lines = [l.strip() for l in tle_text.splitlines() if l.strip()]
                                if len(lines) >= 2:
                                    # Find the TLE lines (start with "1 " and "2 ")
                                    for i in range(len(lines) - 1):
                                        if lines[i].startswith("1 ") and lines[i+1].startswith("2 "):
                                            tle_result = {
                                                "noradId": norad_id,
                                                "name": satname,
                                                "line1": lines[i],
                                                "line2": lines[i+1],
                                            }
                                            break
                        except Exception:
                            pass

                        # Add if TLE found
                        if tle_result and tle_result["line1"] and tle_result["line2"]:
                            results.append(tle_result)

                    if results:
                        return results
    except Exception:
        pass

    return []  # No results found in any source


def _extract_epoch_from_tle_line1(line1: str) -> float:
    """Extract epoch as float from TLE line 1 for comparison (higher = newer)."""
    try:
        epoch_str = line1[18:32]  # YYDDD.DDDDDDDD format
        return float(epoch_str)
    except (ValueError, IndexError):
        return 0.0


@router.get("/tle/{norad_id}")
def fetch_tle(norad_id: str):
    """Fetch TLE for a NORAD ID — queries all sources and returns the newest by epoch."""
    candidates = []  # List of (name, line1, line2, epoch)

    # Source 1: tle.ivanstanojevic.me
    try:
        req = urllib.request.Request(f"{_TLE_API}/{norad_id}", headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            m = _json.loads(r.read())
        if m.get("line1") and m.get("line2"):
            epoch = _extract_epoch_from_tle_line1(m["line1"])
            candidates.append((m["name"], m["line1"], m["line2"], epoch))
    except Exception:
        pass

    # Source 2: CelesTrak
    try:
        req = urllib.request.Request(f"{_CELESTRAK_TLE}?CATNR={norad_id}", headers={"User-Agent": "TASA/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", errors="replace").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        name = norad_id
        line1, line2 = None, None
        if len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
            name, line1, line2 = lines[0], lines[1], lines[2]
        elif len(lines) == 2 and lines[0].startswith("1 ") and lines[1].startswith("2 "):
            line1, line2 = lines[0], lines[1]
        if line1 and line2:
            epoch = _extract_epoch_from_tle_line1(line1)
            candidates.append((name, line1, line2, epoch))
    except Exception:
        pass

    # Source 3: Space-Track gp class (newest TLE)
    try:
        username = os.environ.get("SPACETRACK_USERNAME")
        password = os.environ.get("SPACETRACK_PASSWORD")

        if username and password:
            import requests

            session = requests.Session()
            login_resp = session.post(
                "https://www.space-track.org/ajaxauth/login",
                data={"identity": username, "password": password},
                timeout=10,
            )

            if login_resp.status_code == 200:
                gp_url = f"https://www.space-track.org/basicspacedata/query/class/gp/NORAD_CAT_ID/{norad_id}/orderby/EPOCH%20desc/limit/1/format/tle"
                gp_resp = session.get(gp_url, timeout=10)

                if gp_resp.status_code == 200:
                    text = gp_resp.text.strip()
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
                    if len(lines) >= 2 and lines[0].startswith("1 ") and lines[1].startswith("2 "):
                        satname = norad_id
                        try:
                            satcat_url = f"https://www.space-track.org/basicspacedata/query/class/satcat/NORAD_CAT_ID/{norad_id}/format/json"
                            satcat_resp = session.get(satcat_url, timeout=10)
                            if satcat_resp.status_code == 200:
                                sats = satcat_resp.json()
                                if sats:
                                    satname = sats[0].get("SATNAME", norad_id)
                        except Exception:
                            pass
                        epoch = _extract_epoch_from_tle_line1(lines[0])
                        candidates.append((satname, lines[0], lines[1], epoch))
    except Exception:
        pass

    # Return the newest TLE (highest epoch)
    if candidates:
        candidates.sort(key=lambda x: x[3], reverse=True)  # Sort by epoch, newest first
        name, line1, line2, epoch = candidates[0]
        return {"noradId": norad_id, "name": name, "line1": line1, "line2": line2}

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


@router.post("/tle/{norad_id}/refresh")
def refresh_single_tle(norad_id: str):
    """Fetch fresh TLE from Space-Track for a single satellite and update KG orbital params."""
    from modules.events.event_store import classify_regime

    try:
        # Try to fetch fresh TLE from Space-Track or other sources
        tle_result = fetch_tle(norad_id)
        if not tle_result:
            raise HTTPException(status_code=404, detail=f"Could not fetch TLE for {norad_id}")

        line1 = tle_result["line1"]
        line2 = tle_result["line2"]
        name = tle_result["name"]

        # Update tle_store
        meta = tle_store.upsert(norad_id, name, line1, line2)

        # Update KG orbital params if possible
        def _extract_orbital_period(l1: str, l2: str) -> float | None:
            try:
                mean_motion = float(l2[52:63])
                if mean_motion > 0:
                    return 1440.0 / mean_motion
            except (ValueError, IndexError):
                pass
            return None

        period = _extract_orbital_period(line1, line2)
        orbit_type = classify_regime(period) if period else None

        if norad_id in kg_store.nodes:
            node = kg_store.nodes[norad_id]
            node["updated_at"] = datetime.now(timezone.utc).isoformat()
            if period is not None:
                node["attributes"]["orbital_period"] = {
                    "value": round(period, 2),
                    "event_date": None,
                    "source_id": "spacetrack",
                }
            if orbit_type:
                node["attributes"]["orbit_type"] = {
                    "value": orbit_type,
                    "event_date": None,
                    "source_id": "spacetrack",
                }
            kg_store.save()

        return {
            "norad_id": norad_id,
            "name": name,
            "line1": line1,
            "line2": line2,
            "orbital_period": period,
            "orbit_type": orbit_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh TLE: {str(e)}")


@router.post("/tle/refresh-all")
def refresh_all_tles():
    """Fetch fresh TLEs from external APIs for every satellite in the KG, and update KG orbital params."""
    from modules.events.event_store import classify_regime

    def _extract_orbital_period(line1: str, line2: str) -> float | None:
        """Extract orbital period in minutes from TLE line 2."""
        try:
            mean_motion = float(line2[52:63])  # Revolutions per day
            if mean_motion > 0:
                return 1440.0 / mean_motion
        except (ValueError, IndexError):
            pass
        return None

    def _update_kg_orbital_params(node_id: str, line1: str, line2: str) -> None:
        """Update KG node with orbital_period and orbit_type from TLE."""
        node = kg_store.nodes.get(node_id)
        if not node:
            return
        period = _extract_orbital_period(line1, line2)
        if not period:
            return
        if "attributes" not in node:
            node["attributes"] = {}
        node["attributes"]["orbital_period"] = {
            "value": round(period, 2),
            "source": "tle_refresh",
        }
        regime = classify_regime(period)
        node["attributes"]["orbit_type"] = {
            "value": regime,
            "source": "tle_refresh",
        }

    results = []
    kg_updated = False

    # Get all satellites from KG (not from tle_store which may be empty)
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

        label = node.get("label", norad_id)

        # Try to fetch TLE
        try:
            url = f"{_TLE_API}/{norad_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "TASA/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                m = _json.loads(r.read())
            if m.get("line1") and m.get("line2"):
                tle_store.upsert(norad_id, m["name"], m["line1"], m["line2"])
                _tle_snapshot(norad_id, m["line1"], m["line2"])
                _update_kg_orbital_params(node.get("id"), m["line1"], m["line2"])
                kg_updated = True
                results.append({"norad_id": norad_id, "name": m["name"], "status": "updated"})
                continue
        except Exception:
            pass

        # Fallback to CelesTrak
        try:
            req = urllib.request.Request(f"{_CELESTRAK_TLE}?CATNR={norad_id}", headers={"User-Agent": "TASA/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                text = r.read().decode("utf-8", errors="replace").strip()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if len(lines) >= 3 and lines[1].startswith("1 ") and lines[2].startswith("2 "):
                tle_store.upsert(norad_id, lines[0], lines[1], lines[2])
                _tle_snapshot(norad_id, lines[1], lines[2])
                _update_kg_orbital_params(node.get("id"), lines[1], lines[2])
                kg_updated = True
                results.append({"norad_id": norad_id, "name": lines[0], "status": "updated"})
                continue
            elif len(lines) == 2 and lines[0].startswith("1 ") and lines[1].startswith("2 "):
                tle_store.upsert(norad_id, label, lines[0], lines[1])
                _tle_snapshot(norad_id, lines[0], lines[1])
                _update_kg_orbital_params(node.get("id"), lines[0], lines[1])
                kg_updated = True
                results.append({"norad_id": norad_id, "name": label, "status": "updated"})
                continue
        except Exception:
            pass

        # Last resort: Space-Track
        try:
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
                                tle_store.upsert(norad_id, label, line1, line2)
                                _tle_snapshot(norad_id, line1, line2)
                                _update_kg_orbital_params(node.get("id"), line1, line2)
                                kg_updated = True
                                results.append({"norad_id": norad_id, "name": label, "status": "updated (space-track)"})
                                continue
        except Exception:
            pass

        results.append({"norad_id": norad_id, "name": label, "status": "failed"})

    if kg_updated:
        kg_store.save()

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
