"""
TLE history archive — append-only JSONL per satellite.
Files stored at data/tle_history/{norad_id}.jsonl
Each line: {"fetched_at": ISO8601, "line1": "...", "line2": "..."}
"""
import json
from datetime import datetime, timezone
from pathlib import Path

TLE_HISTORY_DIR = Path("data/tle_history")


def _path(norad_id: str) -> Path:
    TLE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return TLE_HISTORY_DIR / f"{norad_id}.jsonl"


def snapshot(norad_id: str, line1: str, line2: str) -> None:
    """Append current TLE to satellite's history file (deduplicates consecutive identical TLEs)."""
    p = _path(norad_id)
    # Read last entry to avoid duplicating unchanged TLEs
    if p.exists():
        last_line = ""
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                last_line = line
        if last_line:
            try:
                last = json.loads(last_line)
                if last.get("line1") == line1 and last.get("line2") == line2:
                    return  # unchanged — skip
            except (json.JSONDecodeError, KeyError):
                pass

    entry = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "line1": line1,
        "line2": line2,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_closest_before(norad_id: str, dt: datetime) -> dict | None:
    """Return the TLE snapshot closest to but not after dt."""
    p = _path(norad_id)
    if not p.exists():
        return None

    best: dict | None = None
    best_dt: datetime | None = None
    target = dt.astimezone(timezone.utc)

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                fetched = datetime.fromisoformat(entry["fetched_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                if fetched <= target:
                    if best_dt is None or fetched > best_dt:
                        best = entry
                        best_dt = fetched
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    return best


def get_range(norad_id: str, start: datetime, end: datetime) -> list[dict]:
    """Return all snapshots with fetched_at between start and end (inclusive)."""
    p = _path(norad_id)
    if not p.exists():
        return []

    result = []
    s = start.astimezone(timezone.utc)
    e = end.astimezone(timezone.utc)

    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                fetched = datetime.fromisoformat(entry["fetched_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                if s <= fetched <= e:
                    result.append(entry)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    return result
