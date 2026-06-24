"""
JCO report event extractor — uses LLM to extract maneuver and photometric change events.
"""
import json
import os
import re

from openai import AsyncOpenAI
from .event_store import classify_regime

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


def extract_event_id(text: str) -> str | None:
    """Extract Event ID from report text (NOTOS Event ID field).
    Expected format: Event ID: <hex> (e.g. '579a')
    """
    match = re.search(
        r'Event\s+ID[:\s]*</span>(?:.*?<p[^>]*>)?([a-f0-9]+)',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        return match.group(1).strip()
    return None


_SYSTEM_PROMPT = """You are a satellite event extraction specialist. Extract structured event data from JCO (Joint Conjunction Operations) Mission Management Board reports.

## IMPORTANT: Multi-update reports
When sections are labeled [LATEST UPDATE] and [EARLIER UPDATE N]:
- These are timestamped updates to the same report, with the LATEST at the top.
- For any physical event (same satellite, same underlying maneuver/photometric observation),
  extract it ONCE using the most accurate data available — preferring the [LATEST UPDATE] section.
- If the same satellite appears in both [LATEST UPDATE] and an [EARLIER UPDATE], merge them
  into ONE event: take all numeric fields (delta_v, period_change, etc.) from the latest section,
  and set verification_status based on the LATEST UPDATE's language.
- Do NOT create a separate event for [EARLIER UPDATE] entries that describe the same maneuver/photometric
  change already in the [LATEST UPDATE].

Extract three types of events:

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
- verification_status: "verified" if the report says the maneuver is confirmed/verified; "possible" if the report says "possible maneuver" or analysis is ongoing; "detected" if observed but not yet confirmed. Default "detected".
- pol_status: "within_pol" if report says maneuver is within historical pattern of life; "outside_pol" if report says outside POL or anomalous; "unknown" if not stated.
- analyst_assessment: 1–2 sentence direct quote or close paraphrase of the analyst's interpretation of this maneuver (e.g. "station-keeping maneuver within historical pattern of life"). null if not stated.
- pai_summary: The PAI (Prior Activity Intelligence) sentence about this satellite's mission, if present (e.g. "supports military operations; mission believed to support missile early warning, signals intelligence"). null if not present.

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
- verification_status: "verified" / "possible" / "detected" (same rules as maneuver)
- pol_status: "within_pol" if consistent with historical pattern of life; "outside_pol" if anomalous; "return_to_pol" if the change is the satellite returning to its normal state; "unknown" if not stated.
- analyst_assessment: 1–2 sentence analyst interpretation of the photometric change. null if not stated.
- associated_satellite_id: NORAD ID (digits only) of the nearby satellite mentioned as a possible cause (e.g. "51281" from "close approach with USA 325 (51281)"). null if not mentioned.
- associated_satellite_label: name of that nearby satellite (e.g. "USA 325"). null if not mentioned.
- associated_distance_km: distance in km to the associated satellite at time of close approach (numeric). null if not mentioned.
- pai_summary: PAI sentence about this satellite's mission, if present. null if not present.

## 3. LAUNCH events
Extract when the report documents a rocket launch and satellite deployment.

Fields to extract:
- type: always "launch"
- satellite_id: NORAD catalog number if already assigned, else null
- notos_id: provisional NOTOS tracking number (90000–99999 range) if present, else null
- satellite_label: name of the satellite(s) launched (e.g. "PRSC-E03", "Qianfan Jigui Group 10A-R")
- event_date: ISO 8601 launch datetime
- launch_site: name of launch facility (e.g. "Taiyuan Satellite Launch Center")
- launch_vehicle: rocket name as written (e.g. "CZ-6", "Long March 8")
- orbital_inclination: degrees from TLE line 2 if present, else null
- orbital_period: minutes, computed as 1440 / mean_motion if TLE present, else null
- notam_ids: array of NOTAM IDs associated with this launch (e.g. ["A1286/26", "B2268/26"])
- trajectory_zones: array of polygon/circle zones from NOTAMs, same format as NOTAM extractor — each zone has notam_id, shape, vertices or center_lat/center_lon/radius_km, active_start, active_end
- analyst_assessment: analyst's summary sentence about this launch if present, else null
- pai_summary: PAI sentence about the satellite's mission if present, else null

## Output format
Return ONLY a valid JSON array. No prose, no markdown fences. Example:
[
  {
    "type": "maneuver",
    "satellite_id": "63157",
    "satellite_label": "TJS-15",
    "event_date": "2026-04-30T20:59:00Z",
    "delta_v": 0.19,
    "period_change": -0.0008,
    "apogee_change": -0.32,
    "perigee_change": 0.32,
    "inclination_change": -0.0036,
    "verification_status": "verified",
    "pol_status": "within_pol",
    "analyst_assessment": "Station-keeping maneuver within historical pattern of life for this object.",
    "pai_summary": "TJS-15 supports military operations; mission believed to support missile early warning and signals intelligence."
  },
  {
    "type": "photometric_change",
    "satellite_id": "50322",
    "satellite_label": "SY-12 02",
    "event_date": "2026-03-29T02:08:00Z",
    "magnitude_change_min": 1.7,
    "magnitude_change_max": 2.0,
    "magnitude_direction": "dimmer",
    "recovery_date": "2026-03-30",
    "verification_status": "detected",
    "pol_status": "within_pol",
    "analyst_assessment": "Photometric variation consistent with historical pattern of life; satellite has since returned to nominal photometrics.",
    "associated_satellite_id": "62852",
    "associated_satellite_label": "SPAINSAT NG1",
    "associated_distance_km": 130,
    "pai_summary": "SY-12 02 is a China satellite that supports military operations."
  }
]

  {
    "type": "launch",
    "satellite_id": "68835",
    "notos_id": "94220",
    "satellite_label": "PRSC-E03",
    "event_date": "2026-04-25T12:16:00Z",
    "launch_site": "Taiyuan Satellite Launch Center",
    "launch_vehicle": "CZ-6 (Long March 6)",
    "orbital_inclination": 38.0045,
    "orbital_period": 95.6,
    "notam_ids": ["A1286/26"],
    "trajectory_zones": [],
    "analyst_assessment": "Successful launch into planned LEO orbit.",
    "pai_summary": "PRSC-E03 is a Pakistani Earth observation satellite built by SUPARCO."
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
        valid = [e for e in events if isinstance(e, dict) and e.get("type") in ("maneuver", "photometric_change", "launch")]

        # Deduplicate by (satellite_id, day, type) with verification rank preference.
        # When the same event is extracted from different sections (e.g. "possible" detection
        # estimated time vs "verified" confirmed time), keep the higher-confidence version.
        VERIF_RANK = {"verified": 3, "detected": 2, "possible": 1}
        seen: dict[tuple, dict] = {}
        for ev in valid:
            # Use day-level key: same satellite + same day + same type captures updates
            event_date = ev.get("event_date", "") or ""
            day = event_date[:10]  # YYYY-MM-DD
            key = (ev.get("satellite_id", ""), day, ev.get("type", ""))
            if key not in seen:
                seen[key] = ev
            else:
                existing = seen[key]
                # Rank by verification_status first, then by field count
                new_rank = VERIF_RANK.get(ev.get("verification_status"), 0)
                old_rank = VERIF_RANK.get(existing.get("verification_status"), 0)
                new_score = sum(1 for v in ev.values() if v is not None)
                old_score = sum(1 for v in existing.values() if v is not None)
                if new_rank > old_rank or (new_rank == old_rank and new_score > old_score):
                    seen[key] = ev

        deduped = list(seen.values())
        dropped_dupes = len(valid) - len(deduped)
        if dropped_dupes:
            print(f"[jco_extractor] deduplicated {dropped_dupes} duplicate event(s)")
        print(f"[jco_extractor] extracted {len(deduped)} events ({len(events) - len(valid)} invalid dropped)")

        # Extract Event ID from report (if present) and add to all events
        event_id = extract_event_id(text)

        # Normalise trajectory_zone vertices: LLM may return {lat, lon} objects instead of [lat, lon] arrays
        for ev in deduped:
            # Add Event ID from report (useful for deduplicating across multiple report versions)
            if event_id and not ev.get("event_id"):
                ev["event_id"] = event_id

            # Calculate regime from orbital_period if available
            if not ev.get("regime") and ev.get("orbital_period"):
                try:
                    period_min = float(ev.get("orbital_period"))
                    ev["regime"] = classify_regime(period_min)
                except (ValueError, TypeError):
                    pass

            for zone in (ev.get("trajectory_zones") or []):
                if isinstance(zone.get("vertices"), list):
                    zone["vertices"] = [
                        [v["lat"], v["lon"]] if isinstance(v, dict) else v
                        for v in zone["vertices"]
                    ]

        return deduped
    except json.JSONDecodeError as exc:
        print(f"[jco_extractor] JSON parse error: {exc}\nRaw: {raw[:500]}")
        return []
