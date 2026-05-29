"""
JCO report event extractor — uses LLM to extract maneuver and photometric change events.
"""
import json
import os
import re

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


_SYSTEM_PROMPT = """You are a satellite event extraction specialist. Extract structured event data from JCO (Joint Conjunction Operations) Mission Management Board reports.

Extract two types of events:

## 1. MANEUVER events
Each individual physical maneuver is a SEPARATE event — even if multiple satellites or multiple maneuvers per satellite appear in one report.

Fields to extract:
- type: always "maneuver"
- satellite_id: NORAD catalog number (digits only, from parentheses e.g. "(65851)" → "65851"). If not found, derive a slug from the label.
- satellite_label: satellite name as written in the report (e.g. "SHIYAN 30-01")
- event_date: ISO 8601 datetime of the maneuver. Parse "DDMmmHHMMz" format: e.g. "09Apr0731z" with report year → "2026-04-09T07:31:00Z". If year is unclear, use current year.
- delta_v: numeric m/s value (strip "m/s", preserve sign)
- period_change: numeric seconds (strip "secs", preserve sign)
- apogee_change: numeric km (strip "km", preserve sign)
- perigee_change: numeric km (strip "km", preserve sign)
- inclination_change: numeric degrees (strip "degs", preserve sign)

## 2. PHOTOMETRIC_CHANGE events
Each photometric detection per satellite is a SEPARATE event.

Fields to extract:
- type: always "photometric_change"
- satellite_id: NORAD catalog number (digits only)
- satellite_label: satellite name as written
- event_date: ISO 8601 datetime of detection
- magnitude_change_min: lower bound of magnitude change (numeric, e.g. 1.7 from "1.7 - 2 visual magnitude")
- magnitude_change_max: upper bound (numeric, e.g. 2.0)
- magnitude_direction: "dimmer" or "brighter"
- recovery_date: ISO 8601 date string if recovery is mentioned, else null

## Output format
Return ONLY a valid JSON array. No prose, no markdown fences. Example:
[
  {
    "type": "maneuver",
    "satellite_id": "65851",
    "satellite_label": "SHIYAN 30-01",
    "event_date": "2026-04-09T07:31:00Z",
    "delta_v": 2.27,
    "period_change": 1.71,
    "apogee_change": 0.91,
    "perigee_change": 1.83,
    "inclination_change": -0.0
  },
  {
    "type": "photometric_change",
    "satellite_id": "50322",
    "satellite_label": "SHIYAN 12 02",
    "event_date": "2026-03-30T05:13:00Z",
    "magnitude_change_min": 1.7,
    "magnitude_change_max": 2.0,
    "magnitude_direction": "dimmer",
    "recovery_date": "2026-03-30"
  }
]

If no events are found, return [].
"""


async def extract_events_from_jco(text: str, source_meta: dict) -> list[dict]:
    """Extract maneuver and photometric events from JCO report text. Returns list of event dicts."""
    client = _get_client()

    # Truncate to model context limit
    text_excerpt = text[:40000]

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract all satellite events from the following report:\n\n{text_excerpt}"},
        ],
        temperature=0,
        max_tokens=4000,
    )

    raw = (response.choices[0].message.content or "").strip()

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        events = json.loads(raw)
        if not isinstance(events, list):
            print(f"[jco_extractor] unexpected response shape: {type(events)}")
            return []
        # Basic validation: keep only dicts with a known type
        valid = [e for e in events if isinstance(e, dict) and e.get("type") in ("maneuver", "photometric_change")]
        print(f"[jco_extractor] extracted {len(valid)} events ({len(events) - len(valid)} invalid dropped)")
        return valid
    except json.JSONDecodeError as exc:
        print(f"[jco_extractor] JSON parse error: {exc}\nRaw: {raw[:500]}")
        return []
