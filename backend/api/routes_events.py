"""
Satellite event API routes: store and retrieve maneuver / photometric change events.
"""
from fastapi import APIRouter, HTTPException, Query

from modules.events.event_store import event_store
from modules.events.jco_extractor import extract_events_from_jco
from modules.events.notam_extractor import extract_launch_events
from modules.knowledge_graph import source_store
from modules.knowledge_graph.source_store import SOURCES_DIR

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def get_all_events(
    type: str | None = Query(None),
    regime: str | None = Query(None, description="LEO | MEO | GEO | HEO"),
    days: int | None = Query(None, ge=1, description="Limit to events in the past N days"),
    satellite_id: str | None = Query(None),
):
    if regime or days or satellite_id:
        return event_store.query_events(event_type=type, regime=regime, days=days, satellite_id=satellite_id)
    return event_store.get_all(event_type=type)


@router.get("/satellite/{satellite_id}")
def get_satellite_events(satellite_id: str):
    return event_store.get_by_satellite(satellite_id)


@router.post("/extract/{source_id}")
async def extract_events(source_id: str):
    """Re-extract events from an already-stored source document."""
    doc = source_store._load_index().get(source_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    doc_file_rel = doc.get("file", "")
    text_path = SOURCES_DIR / doc_file_rel
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="Source text not found")

    raw = text_path.read_text(encoding="utf-8")
    # If stored as JSON dict (e.g. news articles), extract text field
    try:
        import json as _json
        parsed = _json.loads(raw)
        text = parsed.get("text") or parsed.get("content") or raw
    except Exception:
        text = raw
    events = await extract_events_from_jco(text, doc)
    added = []
    for ev in events:
        ev["source_id"] = source_id
        ev.setdefault("report_title", doc.get("title", ""))
        eid = event_store.add_event(ev)
        added.append(eid)
    return {"extracted": len(added), "event_ids": added}


@router.post("/notam/ingest")
async def ingest_notam_text(body: dict):
    """Parse raw ICAO NOTAM text, extract launch events, and store them."""
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text field required")

    # Collect already-known NOTAM IDs for dedup
    existing_notam_ids: set[str] = set()
    for ev in event_store.get_all(event_type="launch"):
        existing_notam_ids.update(ev.get("notam_ids") or [])

    events = await extract_launch_events(text, {})
    created = []
    for ev in events:
        new_ids = set(ev.get("notam_ids") or [])
        if new_ids and new_ids.issubset(existing_notam_ids):
            continue  # all IDs already stored — skip duplicate
        ids_str = ", ".join(sorted(new_ids)) if new_ids else "unknown"
        ev.setdefault("report_title", f"NOTAM {ids_str}")
        eid = event_store.add_event(ev)
        ev["id"] = eid
        created.append(ev)

    return {"count": len(created), "events": created}


@router.get("/notam")
def get_notam_events():
    """Return all stored launch events (NOTAM-sourced)."""
    return event_store.get_all(event_type="launch")


@router.delete("/{event_id}")
def delete_event(event_id: str):
    if event_store.delete(event_id):
        return {"deleted": event_id}
    raise HTTPException(status_code=404, detail="Event not found")
