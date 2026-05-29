"""
Ground track coverage analysis — compute satellite passes over geographic regions.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from modules.propagation import sgp4_propagator

REGIONS: dict[str, dict] = {
    "taiwan": {"lat_min": 21.5, "lat_max": 25.5, "lon_min": 119.0, "lon_max": 122.5},
    "south_china_sea": {"lat_min": 3.0, "lat_max": 22.0, "lon_min": 105.0, "lon_max": 120.0},
    "east_china_sea": {"lat_min": 23.0, "lat_max": 33.0, "lon_min": 119.0, "lon_max": 130.0},
    "korean_peninsula": {"lat_min": 34.0, "lat_max": 43.0, "lon_min": 124.0, "lon_max": 130.0},
    "persian_gulf": {"lat_min": 22.0, "lat_max": 30.0, "lon_min": 48.0, "lon_max": 60.0},
    "ukraine": {"lat_min": 44.0, "lat_max": 52.5, "lon_min": 22.0, "lon_max": 40.5},
}


def _in_region(lat: float, lon: float, region: dict) -> bool:
    return (
        region["lat_min"] <= lat <= region["lat_max"]
        and region["lon_min"] <= lon <= region["lon_max"]
    )


def compute_passes(
    line1: str,
    line2: str,
    region: dict,
    days: int = 7,
    step_seconds: int = 60,
) -> list[dict]:
    """Return list of passes over the region bounding box.

    Each pass: {entry_time, exit_time, duration_sec, min_lat, max_lat, min_lon, max_lon}
    """
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now
    end = now + timedelta(days=days)

    positions = sgp4_propagator.get_positions(line1, line2, start, end, step_seconds)

    passes: list[dict] = []
    in_pass = False
    entry_time: Optional[str] = None
    lats: list[float] = []
    lons: list[float] = []

    for pos in positions:
        inside = _in_region(pos.lat, pos.lon, region)
        if inside and not in_pass:
            in_pass = True
            entry_time = datetime.fromtimestamp(pos.timestamp / 1000, tz=timezone.utc).isoformat()
            lats = [pos.lat]
            lons = [pos.lon]
        elif inside and in_pass:
            lats.append(pos.lat)
            lons.append(pos.lon)
        elif not inside and in_pass:
            in_pass = False
            exit_time = datetime.fromtimestamp(pos.timestamp / 1000, tz=timezone.utc).isoformat()
            duration = len(lats) * step_seconds
            passes.append({
                "entry_time": entry_time,
                "exit_time": exit_time,
                "duration_sec": duration,
                "min_lat": round(min(lats), 3),
                "max_lat": round(max(lats), 3),
                "min_lon": round(min(lons), 3),
                "max_lon": round(max(lons), 3),
            })

    # Close any open pass at end of window
    if in_pass and lats:
        exit_time = datetime.fromtimestamp(positions[-1].timestamp / 1000, tz=timezone.utc).isoformat()
        passes.append({
            "entry_time": entry_time,
            "exit_time": exit_time,
            "duration_sec": len(lats) * step_seconds,
            "min_lat": round(min(lats), 3),
            "max_lat": round(max(lats), 3),
            "min_lon": round(min(lons), 3),
            "max_lon": round(max(lons), 3),
        })

    return passes


def passes_summary(passes: list[dict], days: int) -> dict:
    """Aggregate statistics over a list of passes."""
    if not passes:
        return {
            "total_passes": 0,
            "avg_passes_per_day": 0.0,
            "avg_duration_min": 0.0,
            "revisit_interval_hours": None,
        }

    total = len(passes)
    avg_per_day = round(total / days, 2)
    avg_dur = round(sum(p["duration_sec"] for p in passes) / total / 60, 1)

    # Revisit interval: average time between consecutive pass starts
    if total > 1:
        starts = sorted(p["entry_time"] for p in passes)
        intervals = []
        for i in range(1, len(starts)):
            try:
                a = datetime.fromisoformat(starts[i - 1])
                b = datetime.fromisoformat(starts[i])
                intervals.append((b - a).total_seconds() / 3600)
            except ValueError:
                pass
        revisit = round(sum(intervals) / len(intervals), 1) if intervals else None
    else:
        revisit = None

    return {
        "total_passes": total,
        "avg_passes_per_day": avg_per_day,
        "avg_duration_min": avg_dur,
        "revisit_interval_hours": revisit,
    }
