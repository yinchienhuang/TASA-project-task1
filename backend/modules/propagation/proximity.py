"""
Minimum-distance calculation between two satellites over a time window.
Distances are computed in ECEF (km) for accuracy.
Uses continuous optimization (scipy) to find exact minimum, not just sampling.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import minimize_scalar
from sgp4.api import Satrec, jday

from .sgp4_propagator import _jday_from_dt, _gmst


@dataclass
class ProximityResult:
    min_distance_km: float
    at_time: int          # Unix ms
    sat1_pos: dict        # {lat, lon, alt} at closest approach
    sat2_pos: dict


def _teme_to_ecef(r_km: np.ndarray, jd_full: float) -> np.ndarray:
    """Rotate TEME vector to ECEF using GMST."""
    gmst = _gmst(jd_full)
    cg, sg = math.cos(gmst), math.sin(gmst)
    return np.array([
        r_km[0] * cg + r_km[1] * sg,
        -r_km[0] * sg + r_km[1] * cg,
        r_km[2],
    ])


def _distance_at_time(unix_seconds: float, sat_a: Satrec, sat_b: Satrec) -> float:
    """Calculate distance between two satellites at a given Unix timestamp."""
    dt = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    jd, fr = _jday_from_dt(dt)

    ea, ra, _ = sat_a.sgp4(jd, fr)
    eb, rb, _ = sat_b.sgp4(jd, fr)

    if ea != 0 or eb != 0:
        return float("inf")

    ra_ecef = _teme_to_ecef(np.array(ra), jd + fr)
    rb_ecef = _teme_to_ecef(np.array(rb), jd + fr)

    return float(np.linalg.norm(ra_ecef - rb_ecef))


def min_distance(
    line1_a: str, line2_a: str,
    line1_b: str, line2_b: str,
    start: datetime, end: datetime,
    step_seconds: int = 60,
) -> ProximityResult | None:
    """
    Find minimum distance between two satellites using continuous optimization.
    First samples coarsely to find the approximate region, then refines with scipy.
    Returns the closest approach distance, time, and positions.
    """
    sat_a = Satrec.twoline2rv(line1_a, line2_a)
    sat_b = Satrec.twoline2rv(line1_b, line2_b)

    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)

    start_ts = start_utc.timestamp()
    end_ts = end_utc.timestamp()

    # Step 1: Coarse sampling to find approximate minimum region
    best_dist = float("inf")
    best_time_ts = start_ts

    dt = start_utc
    step = timedelta(seconds=max(step_seconds, 10))  # At least 10-second sampling

    while dt <= end_utc:
        ts = dt.timestamp()
        dist = _distance_at_time(ts, sat_a, sat_b)
        if dist < best_dist:
            best_dist = dist
            best_time_ts = ts
        dt += step

    if best_dist == float("inf"):
        return None

    # Step 2: Refine using scipy optimization in a window around the best point
    # Search in a ±5 minute window around the coarse minimum
    window_seconds = 300
    search_start = max(start_ts, best_time_ts - window_seconds)
    search_end = min(end_ts, best_time_ts + window_seconds)

    def distance_for_opt(ts):
        if ts < search_start or ts > search_end:
            return float("inf")
        return _distance_at_time(ts, sat_a, sat_b)

    try:
        result = minimize_scalar(
            distance_for_opt,
            bounds=(search_start, search_end),
            method='bounded',
            options={'xatol': 0.1}  # Precision: 0.1 second
        )
        refined_time_ts = result.x
        refined_dist = result.fun
    except Exception:
        # Fallback to coarse result if optimization fails
        refined_time_ts = best_time_ts
        refined_dist = best_dist

    # Step 3: Get positions at the optimal time
    dt_optimal = datetime.fromtimestamp(refined_time_ts, tz=timezone.utc)
    jd, fr = _jday_from_dt(dt_optimal)

    ea, ra, _ = sat_a.sgp4(jd, fr)
    eb, rb, _ = sat_b.sgp4(jd, fr)

    if ea == 0 and eb == 0:
        ra_ecef = _teme_to_ecef(np.array(ra), jd + fr)
        rb_ecef = _teme_to_ecef(np.array(rb), jd + fr)
    else:
        ra_ecef = rb_ecef = np.zeros(3)

    return ProximityResult(
        min_distance_km=round(refined_dist, 3),
        at_time=int(refined_time_ts * 1000),
        sat1_pos={"x_km": round(float(ra_ecef[0]), 3),
                  "y_km": round(float(ra_ecef[1]), 3),
                  "z_km": round(float(ra_ecef[2]), 3)},
        sat2_pos={"x_km": round(float(rb_ecef[0]), 3),
                  "y_km": round(float(rb_ecef[1]), 3),
                  "z_km": round(float(rb_ecef[2]), 3)},
    )
