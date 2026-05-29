"""
Minimum-distance calculation between two satellites over a time window.
Distances are computed in ECEF (km) for accuracy.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
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


def min_distance(
    line1_a: str, line2_a: str,
    line1_b: str, line2_b: str,
    start: datetime, end: datetime,
    step_seconds: int = 60,
) -> ProximityResult | None:
    """
    Sample both satellites at `step_seconds` intervals over [start, end].
    Returns the closest approach distance and time.
    """
    sat_a = Satrec.twoline2rv(line1_a, line2_a)
    sat_b = Satrec.twoline2rv(line1_b, line2_b)

    best_dist = float("inf")
    best_time = 0
    best_ra = best_rb = np.zeros(3)

    dt = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    step = timedelta(seconds=step_seconds)

    while dt <= end_utc:
        jd, fr = _jday_from_dt(dt)
        ea, ra, _ = sat_a.sgp4(jd, fr)
        eb, rb, _ = sat_b.sgp4(jd, fr)
        if ea == 0 and eb == 0:
            ra_ecef = _teme_to_ecef(np.array(ra), jd + fr)
            rb_ecef = _teme_to_ecef(np.array(rb), jd + fr)
            dist = float(np.linalg.norm(ra_ecef - rb_ecef))
            if dist < best_dist:
                best_dist = dist
                best_time = int(dt.timestamp() * 1000)
                best_ra, best_rb = ra_ecef, rb_ecef
        dt += step

    if best_dist == float("inf"):
        return None

    return ProximityResult(
        min_distance_km=round(best_dist, 3),
        at_time=best_time,
        sat1_pos={"x_km": round(float(best_ra[0]), 3),
                  "y_km": round(float(best_ra[1]), 3),
                  "z_km": round(float(best_ra[2]), 3)},
        sat2_pos={"x_km": round(float(best_rb[0]), 3),
                  "y_km": round(float(best_rb[1]), 3),
                  "z_km": round(float(best_rb[2]), 3)},
    )
