"""
EventStore: JSON-persisted satellite event store (maneuvers, photometric changes).
"""
import json
import pathlib
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

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
        # Fields to ignore when computing diffs
        self._ignore_diff_fields = {"id", "created_at", "update_history"}
        # Fields that indicate a significant update
        self._significant_fields = {
            "verification_status", "delta_v", "satellite_id",
            "event_date", "rocket_id", "rocket_label", "event_id"
        }

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

    def _compute_diff(self, old: dict, new: dict) -> dict:
        """Compute field-level differences between two events."""
        changes = []
        all_keys = set(old.keys()) | set(new.keys())

        for key in sorted(all_keys):
            if key in self._ignore_diff_fields:
                continue

            old_val = old.get(key)
            new_val = new.get(key)

            if old_val != new_val:
                if key not in old:
                    change_type = "added"
                elif key not in new:
                    change_type = "removed"
                else:
                    change_type = "updated"

                changes.append({
                    "field": key,
                    "old": old_val,
                    "new": new_val,
                    "type": change_type
                })

        return changes

    def _summarize_changes(self, changes: list) -> str:
        """Generate human-readable summary of changes."""
        added = sum(1 for c in changes if c["type"] == "added")
        updated = sum(1 for c in changes if c["type"] == "updated")
        removed = sum(1 for c in changes if c["type"] == "removed")

        parts = []
        if added:
            parts.append(f"{added} field(s) added")
        if updated:
            parts.append(f"{updated} field(s) updated")
        if removed:
            parts.append(f"{removed} field(s) removed")

        return ", ".join(parts) if parts else "no changes"

    def _is_significant_update(self, changes: list) -> bool:
        """Determine if update contains important field changes."""
        for change in changes:
            if change["field"] in self._significant_fields:
                return True
        return len(changes) > 3

    def _is_better(self, new: dict, existing: dict) -> bool:
        """Determine if new event should replace existing."""
        VERIF_RANK = {"verified": 3, "detected": 2, "possible": 1}

        new_count = sum(1 for v in new.values() if v is not None)
        old_count = sum(1 for v in existing.values() if v is not None)

        new_rank = VERIF_RANK.get(new.get("verification_status"), 0)
        old_rank = VERIF_RANK.get(existing.get("verification_status"), 0)

        return new_rank > old_rank or (new_rank == old_rank and new_count > old_count)

    @property
    def events(self) -> dict:
        self._load()
        return self._data["events"]

    def add_event(self, event: dict) -> dict:
        """Add or update event, with detailed change tracking.
        Returns:
        {
            "event_id": str,
            "created": bool,
            "updated": bool,
            "update_info": {
                "timestamp": str,
                "changes": list,
                "summary": str,
                "is_significant": bool
            } | None
        }
        """
        eid = event.get("id") or f"evt_{uuid.uuid4().hex[:8]}"
        event["id"] = eid
        event.setdefault("created_at", _now())

        with self._lock:
            # Priority 1: Check for same event_id (from NOTOS report Event ID field)
            event_id_val = event.get("event_id")
            if event_id_val:
                for existing_id, existing in self.events.items():
                    if existing.get("event_id") == event_id_val:
                        # Same NOTOS event ID — check if update is needed
                        if self._is_better(event, existing):
                            # Compute diff
                            changes = self._compute_diff(existing, event)
                            if changes:
                                summary = self._summarize_changes(changes)
                                is_significant = self._is_significant_update(changes)

                                # Track update history
                                if "update_history" not in existing:
                                    existing["update_history"] = []

                                existing["update_history"].append({
                                    "timestamp": _now(),
                                    "changes": changes,
                                    "summary": summary
                                })

                                # Update fields from new event
                                for change in changes:
                                    if change["type"] != "removed":
                                        existing[change["field"]] = change["new"]

                                self.save()
                                return {
                                    "event_id": existing_id,
                                    "created": False,
                                    "updated": True,
                                    "update_info": {
                                        "timestamp": _now(),
                                        "changes": changes,
                                        "summary": summary,
                                        "is_significant": is_significant
                                    }
                                }
                        # Existing is better, don't update
                        return {
                            "event_id": existing_id,
                            "created": False,
                            "updated": False,
                            "update_info": None
                        }

            # Priority 2: Fall back to (satellite_id, day, type) dedup
            key = (
                str(event.get("satellite_id") or ""),
                str(event.get("event_date") or ""),
                str(event.get("type") or ""),
            )

            if key != ("", "", "") and key[1]:  # need at least event_date
                for existing_id, existing in self.events.items():
                    existing_key = (
                        str(existing.get("satellite_id") or ""),
                        str(existing.get("event_date") or ""),
                        str(existing.get("type") or ""),
                    )
                    # Match on exact key OR same-day-same-satellite-same-type
                    same_event = (
                        existing_key == key  # exact match (same time)
                        or (
                            key[0] == existing_key[0]  # same satellite
                            and key[2] == existing_key[2]  # same type
                            and key[1][:10] == existing_key[1][:10]  # same day
                        )
                    )
                    if same_event:
                        # Potential duplicate
                        if self._is_better(event, existing):
                            changes = self._compute_diff(existing, event)
                            if changes:
                                summary = self._summarize_changes(changes)
                                is_significant = self._is_significant_update(changes)

                                if "update_history" not in existing:
                                    existing["update_history"] = []

                                existing["update_history"].append({
                                    "timestamp": _now(),
                                    "changes": changes,
                                    "summary": summary
                                })

                                for change in changes:
                                    if change["type"] != "removed":
                                        existing[change["field"]] = change["new"]

                                self.save()
                                return {
                                    "event_id": existing_id,
                                    "created": False,
                                    "updated": True,
                                    "update_info": {
                                        "timestamp": _now(),
                                        "changes": changes,
                                        "summary": summary,
                                        "is_significant": is_significant
                                    }
                                }
                        # Old is better, discard new
                        return {
                            "event_id": existing_id,
                            "created": False,
                            "updated": False,
                            "update_info": None
                        }

            # New event
            self.events[eid] = event
            self.save()
            return {
                "event_id": eid,
                "created": True,
                "updated": False,
                "update_info": None
            }

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
