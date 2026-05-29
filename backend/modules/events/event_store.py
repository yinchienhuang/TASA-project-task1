"""
EventStore: JSON-persisted satellite event store (maneuvers, photometric changes).
"""
import json
import pathlib
import threading
import uuid
from datetime import datetime, timedelta, timezone

EVENTS_FILE = pathlib.Path(__file__).parents[3] / "data" / "events" / "events.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def classify_regime(orbital_period_min: float) -> str:
    if orbital_period_min < 127:
        return "LEO"
    if orbital_period_min < 600:
        return "MEO"
    if orbital_period_min < 1500:
        return "GEO"
    return "HEO"


class EventStore:
    def __init__(self):
        self._data: dict = {}
        self._lock = threading.Lock()

    def _load(self) -> None:
        if not self._data:
            if EVENTS_FILE.exists():
                self._data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
            else:
                self._data = {"events": {}}

    def save(self) -> None:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        EVENTS_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @property
    def events(self) -> dict:
        self._load()
        return self._data["events"]

    def add_event(self, event: dict) -> str:
        eid = event.get("id") or f"evt_{uuid.uuid4().hex[:8]}"
        event["id"] = eid
        event.setdefault("created_at", _now())
        with self._lock:
            self.events[eid] = event
            self.save()
        return eid

    def get_by_satellite(self, satellite_id: str) -> list[dict]:
        return sorted(
            [e for e in self.events.values() if e.get("satellite_id") == satellite_id],
            key=lambda e: e.get("event_date", ""),
            reverse=True,
        )

    def get_all(self, event_type: str | None = None) -> list[dict]:
        evts = list(self.events.values())
        if event_type:
            evts = [e for e in evts if e.get("type") == event_type]
        return sorted(evts, key=lambda e: e.get("event_date", ""), reverse=True)

    def query_events(
        self,
        event_type: str | None = None,
        regime: str | None = None,
        days: int | None = None,
        satellite_id: str | None = None,
    ) -> list[dict]:
        """Fleet-level filter over all events. O(n) scan — fast enough for <10k events."""
        self._load()
        events = list(self._data["events"].values())
        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        if regime:
            events = [e for e in events if e.get("regime") == regime]
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            events = [
                e for e in events
                if (_parse_dt(e.get("event_date", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
            ]
        if satellite_id:
            events = [e for e in events if e.get("satellite_id") == satellite_id]
        return sorted(events, key=lambda e: e.get("event_date", ""), reverse=True)

    def delete(self, event_id: str) -> bool:
        with self._lock:
            if event_id in self.events:
                del self.events[event_id]
                self.save()
                return True
        return False


event_store = EventStore()
