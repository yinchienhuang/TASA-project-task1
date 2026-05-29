"""
EvolutionTracker: append-only event log sorted by real-world event_date.
"""
import json
import pathlib
from datetime import datetime, timezone

EVOLUTION_FILE = pathlib.Path(__file__).parents[3] / "data" / "kg" / "evolution.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(event: dict) -> None:
    """Append one event to evolution.jsonl. event must include event_date."""
    if "ingested_at" not in event:
        event["ingested_at"] = _now()
    EVOLUTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EVOLUTION_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_all() -> list[dict]:
    if not EVOLUTION_FILE.exists():
        return []
    events = []
    with open(EVOLUTION_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def get_entity_history(entity_id: str) -> list[dict]:
    """All events for an entity, sorted by event_date ASC (real-world timeline)."""
    events = [
        e for e in _read_all()
        if e.get("entity_id") == entity_id or e.get("edge_id", "").startswith(f"e_{entity_id}_")
    ]
    return sorted(events, key=lambda e: e.get("event_date") or "")


def get_all_events() -> list[dict]:
    return sorted(_read_all(), key=lambda e: e.get("event_date") or "")


def generate_report(entity_id: str) -> str:
    """Chronological narrative for an entity ordered by event_date."""
    history = get_entity_history(entity_id)
    if not history:
        return f"No evolution history found for entity '{entity_id}'."
    lines = [f"Evolution history for {entity_id}:", ""]
    for event in history:
        date = event.get("event_date") or event.get("ingested_at", "unknown date")
        change = event.get("change_type", "unknown")
        source = event.get("source_id", "")
        approx = " (approx.)" if event.get("event_date_approximate") else ""
        if change == "node_added":
            lines.append(f"{date}{approx} — Entity added (source: {source})")
        elif change == "edge_added":
            lines.append(f"{date}{approx} — Relationship added: {event.get('edge_id', '')} (source: {source})")
        elif change == "attribute_filled":
            lines.append(f"{date}{approx} — {event.get('field')} set to '{event.get('value')}' (source: {source})")
        elif change == "attribute_changed":
            lines.append(f"{date}{approx} — {event.get('field')} changed from '{event.get('old_value')}' to '{event.get('new_value')}' (source: {source})")
        elif change == "conflict_detected":
            lines.append(f"{date}{approx} — Conflict detected: {event.get('llm_assessment', '')[:80]}...")
        elif change == "source_added":
            lines.append(f"{date}{approx} — Additional source confirmed: {source}")
        else:
            lines.append(f"{date}{approx} — {change} (source: {source})")
    return "\n".join(lines)
