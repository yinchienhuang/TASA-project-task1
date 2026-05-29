"""
In-memory TLE registry.
Populated at startup from the KG via _sync_tle_from_kg() in main.py.
"""
from dataclasses import dataclass

@dataclass
class SatelliteMeta:
    norad_id: str
    name: str
    line1: str
    line2: str

_STORE: dict[str, SatelliteMeta] = {}


def get(norad_id: str) -> SatelliteMeta | None:
    return _STORE.get(norad_id)


def all_satellites() -> list[SatelliteMeta]:
    return list(_STORE.values())


def upsert(norad_id: str, name: str, line1: str, line2: str) -> SatelliteMeta:
    meta = SatelliteMeta(norad_id=norad_id, name=name, line1=line1, line2=line2)
    _STORE[norad_id] = meta
    return meta
