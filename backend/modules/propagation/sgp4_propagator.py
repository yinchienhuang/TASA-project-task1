"""
SGP4 orbit propagation with TEME → geodetic coordinate conversion.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4.api import Satrec, jday


@dataclass
class Position:
    lat: float        # degrees
    lon: float        # degrees
    alt: float        # km above ellipsoid
    timestamp: int    # Unix ms


def _jday_from_dt(dt: datetime) -> tuple[float, float]:
    dt = dt.astimezone(timezone.utc)
    jd, fr = jday(dt.year, dt.month, dt.day,
                  dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)
    return jd, fr


def _gmst(jd_ut1: float) -> float:
    """Greenwich Mean Sidereal Time in radians."""
    T = (jd_ut1 - 2451545.0) / 36525.0
    theta_sec = (67310.54841
                 + (876600 * 3600 + 8640184.812866) * T
                 + 0.093104 * T ** 2
                 - 6.2e-6 * T ** 3)
    return math.radians((theta_sec % 86400) / 240.0)


def _teme_to_geodetic(r_km: np.ndarray, jd_full: float) -> tuple[float, float, float]:
    """
    Convert TEME position vector (km) to geodetic lat, lon (degrees), alt (km).
    Uses GMST for TEME→ECEF rotation, then Bowring's iterative method.
    """
    gmst = _gmst(jd_full)
    cg, sg = math.cos(gmst), math.sin(gmst)

    # TEME → ECEF
    x = r_km[0] * cg + r_km[1] * sg
    y = -r_km[0] * sg + r_km[1] * cg
    z = float(r_km[2])

    # WGS-84 constants (km)
    a = 6378.137
    e2 = 6.6943799901e-3

    lon = math.atan2(y, x)
    p = math.hypot(x, y)

    # Iterative Bowring method for lat
    lat = math.atan2(z, p * (1.0 - e2))
    for _ in range(10):
        N = a / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
        lat_new = math.atan2(z + e2 * N * math.sin(lat), p)
        if abs(lat_new - lat) < 1e-12:
            lat = lat_new
            break
        lat = lat_new

    N = a / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    cos_lat = math.cos(lat)
    alt = (p / cos_lat - N) if abs(cos_lat) > 1e-10 else (abs(z) / abs(math.sin(lat)) - N * (1.0 - e2))

    return math.degrees(lat), math.degrees(lon), alt


def get_position(line1: str, line2: str, dt: datetime) -> Position | None:
    """Propagate a single satellite to `dt`, return geodetic position."""
    sat = Satrec.twoline2rv(line1, line2)
    jd, fr = _jday_from_dt(dt)
    e, r, _ = sat.sgp4(jd, fr)
    if e != 0:
        return None
    lat, lon, alt = _teme_to_geodetic(np.array(r), jd + fr)
    return Position(lat=lat, lon=lon, alt=alt,
                    timestamp=int(dt.astimezone(timezone.utc).timestamp() * 1000))


def get_positions(line1: str, line2: str,
                  start: datetime, end: datetime,
                  step_seconds: int = 60) -> list[Position]:
    """Propagate over [start, end] at fixed step, return list of positions."""
    sat = Satrec.twoline2rv(line1, line2)
    results: list[Position] = []
    dt = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    step = timedelta(seconds=step_seconds)

    while dt <= end_utc:
        jd, fr = _jday_from_dt(dt)
        e, r, _ = sat.sgp4(jd, fr)
        if e == 0:
            lat, lon, alt = _teme_to_geodetic(np.array(r), jd + fr)
            results.append(Position(
                lat=lat, lon=lon, alt=alt,
                timestamp=int(dt.timestamp() * 1000),
            ))
        dt += step

    return results
