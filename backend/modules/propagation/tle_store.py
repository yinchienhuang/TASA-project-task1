"""
In-memory TLE registry with file persistence.
Loads from data/tle/*.json on startup.
"""
import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone

TLE_DIR = pathlib.Path(__file__).parents[3] / "data" / "tle"

@dataclass
class SatelliteMeta:
    norad_id: str
    name: str
    line1: str
    line2: str

_STORE: dict[str, SatelliteMeta] = {}


def load_from_disk():
    """Load all TLE files from data/tle/ into memory."""
    global _STORE
    _STORE.clear()

    TLE_DIR.mkdir(parents=True, exist_ok=True)

    for tle_file in TLE_DIR.glob("*.json"):
        try:
            data = json.loads(tle_file.read_text(encoding="utf-8"))
            norad_id = data.get("norad_id")
            if norad_id:
                meta = SatelliteMeta(
                    norad_id=norad_id,
                    name=data.get("name", norad_id),
                    line1=data.get("line1", ""),
                    line2=data.get("line2", "")
                )
                _STORE[norad_id] = meta
        except Exception as e:
            print(f"Warning: failed to load TLE from {tle_file}: {e}")


def get(norad_id: str) -> SatelliteMeta | None:
    return _STORE.get(norad_id)


def all_satellites() -> list[SatelliteMeta]:
    return list(_STORE.values())


def upsert(norad_id: str, name: str, line1: str, line2: str) -> SatelliteMeta:
    """Add/update TLE in memory and save to file."""
    meta = SatelliteMeta(norad_id=norad_id, name=name, line1=line1, line2=line2)
    _STORE[norad_id] = meta

    # Save to file
    _save_to_disk(norad_id, name, line1, line2)
    return meta


def _save_to_disk(norad_id: str, name: str, line1: str, line2: str):
    """Save a single TLE to data/tle/{norad_id}.json."""
    try:
        TLE_DIR.mkdir(parents=True, exist_ok=True)
        tle_file = TLE_DIR / f"{norad_id}.json"

        data = {
            "norad_id": norad_id,
            "name": name,
            "line1": line1,
            "line2": line2,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

        tle_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"Warning: failed to save TLE {norad_id} to disk: {e}")
