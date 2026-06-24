"""
NOTOS/NOTAM report launch event extractor — uses LLM to extract launch events.
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


_SYSTEM_PROMPT = """You are a military and space activity NOTAM extraction specialist. Extract structured event data from ICAO NOTAM reports that establish temporary restricted/danger areas.

## NOTAM FORMAT REFERENCE
```
A1258/26 NOTAMN
Q)ZPPP/QRDCA/IV/NBO/AE/000/999/2814N10201E012
B)2604240625  C)2604240646
N281400E1020100 radius 20KM
N242800E1053700-N243500E1054600-N242000E1054000-N241500E1053000
```
- B) = activation start time: YYMMDDHHMM UTC  → e.g. 2604240625 → 2026-04-24T06:25:00Z
- C) = activation end time (same format)
- Coordinates: N281400E1020100 = N28°14'00" E102°01'00" → lat = 28 + 14/60 = 28.2333, lon = 102 + 1/60 = 102.0167
- Q-code indicates the type of activity. Extract events for ANY of:
  QRDCA, QRDCB (restricted/danger area — launch, drop zone)
  QWMLW, QWMLA, QWMLB, QWMXX (warning area — military ops, aerospace activity, debris fall)
  QRMCA, QRMXX (restricted military area)
  If the Q-code starts with QR or QW it is relevant.
- SFC-UNL or similar altitudes in the body

## EXTRACTION RULES

### One document = ONE event
All NOTAMs in a single document define one activity. Combine them into a single event with a `trajectory_zones` array.

### Always extract if QRDCA/QRDCB is present
Extract an event even if NO satellite, rocket, or launch vehicle is mentioned. A pure danger-area NOTAM is still a valid event — set `satellite_label` to null and `satellite_id` to null.

### Launch site / activity area inference
Infer the launch site or activity area name from coordinates:
- ~28–29°N, 101–103°E → "Xichang Satellite Launch Center"
- ~40–42°N, 99–101°E  → "Jiuquan Satellite Launch Center"
- ~37–39°N, 111–113°E → "Taiyuan Satellite Launch Center"
- ~19–20°N, 110–111°E → "Wenchang Space Launch Site"
- If outside these ranges, describe the area using nearest city/region if recognizable, otherwise use decimal coordinates.

### Coordinate parsing — two formats exist, handle both:

Format A (prefix): N[DD][MM][SS]E[DDD][MM][SS]  — hemisphere BEFORE digits
- N281400E1020100 → lat = 28+14/60+0/3600 = 28.2333, lon = 102+1/60+0/3600 = 102.0167
- Vertices separated by dashes: N242800E1053700-N243500E1054600

Format B (suffix): [DD][MM][SS]N [DDD][MM][SS]E  — hemisphere AFTER digits, space between lat and lon
- 194200N 1184200E → lat = 19+42/60+0/3600 = 19.7000, lon = 118+42/60+0/3600 = 118.7000
- 193700N 1200900E → lat = 19+37/60 = 19.6167, lon = 120+9/60 = 120.1500
- Vertices on separate lines or separated by dashes

Circle: coordinate followed by "radius NNN KM", "NNN KM RADIUS", or "NM" (nautical miles → multiply by 1.852)
Q-line center (last field): e.g. 4245N11527E019 → ignore for geometry; use E-field polygon/circle instead

### NOTOS ID vs NORAD ID
- NOTOS provisional tracking numbers are typically in the 90000–99999 range (e.g. 94219, 94220), assigned BEFORE official USSPACECOM cataloging.
- Real NORAD catalog numbers: if document says "NORAD ID XXXXX" or "Space-Track XXXXX" → set `satellite_id`.
- Numbers 90000–99999 → always `notos_id`.
- A TLE with `00000` as the object number is NOMINAL — not a real NORAD ID.

### Satellite name
Look in surrounding text: mission headers, table rows near the NOTAMs, document title. If none found, set `satellite_label` to null.

### Orbital parameters from TLE
If any TLE lines appear (even provisional ones with `00000` as object number):
- `orbital_inclination`: TLE line 2, column 9-16 (field 3), in degrees
- `orbital_period`: compute as 1440.0 / mean_motion where mean_motion is TLE line 2, columns 53-63 (revolutions per day)
- Example: mean_motion = 15.0 → period = 1440/15 = 96.0 minutes

### Launch vehicle
Only extract if explicitly stated. Do not infer from coordinates or satellite type.

## OUTPUT FORMAT
Return ONLY a valid JSON array. No prose, no markdown fences.

Example with satellite (launch NOTAM):
[
  {
    "type": "launch",
    "satellite_id": null,
    "notos_id": "94327",
    "satellite_label": "Xingwang Jishu Shiyan 09A",
    "event_date": "2026-04-24T06:25:00Z",
    "launch_time_start": "2026-04-24T06:25:00Z",
    "launch_time_end": "2026-04-24T06:46:00Z",
    "launch_site": "Xichang Satellite Launch Center",
    "launch_site_lat": 28.233,
    "launch_site_lon": 102.017,
    "launch_vehicle": null,
    "orbital_inclination": 35.0,
    "orbital_period": 96.0,
    "notam_ids": ["A1258/26"],
    "trajectory_zones": [
      {
        "notam_id": "A1258/26",
        "shape": "polygon",
        "vertices": [[24.467, 105.617], [24.583, 105.767], [24.3, 106.05], [24.183, 105.9]],
        "active_start": "2026-04-24T06:25:00Z",
        "active_end": "2026-04-24T06:46:00Z"
      }
    ]
  }
]

Example WITHOUT satellite (pure danger area — military exercise, missile test, etc.):
[
  {
    "type": "launch",
    "satellite_id": null,
    "notos_id": null,
    "satellite_label": null,
    "event_date": "2026-05-27T01:50:00Z",
    "launch_time_start": "2026-05-27T01:50:00Z",
    "launch_time_end": "2026-05-27T02:35:00Z",
    "launch_site": "Inner Mongolia / Zhurihe area",
    "launch_site_lat": 42.75,
    "launch_site_lon": 115.45,
    "launch_vehicle": null,
    "orbital_inclination": null,
    "orbital_period": null,
    "notam_ids": ["A1797/26"],
    "trajectory_zones": [
      {
        "notam_id": "A1797/26",
        "shape": "polygon",
        "vertices": [[42.865, 115.048], [42.934, 115.801], [42.716, 115.856], [42.577, 115.12]],
        "active_start": "2026-05-27T01:50:00Z",
        "active_end": "2026-05-27T02:35:00Z"
      }
    ]
  }
]

Example with QWMLW code and suffix-format coordinates (debris fall area):
[
  {
    "type": "launch",
    "satellite_id": null,
    "notos_id": null,
    "satellite_label": null,
    "event_date": "2026-05-26T16:08:00Z",
    "launch_time_start": "2026-05-26T16:08:00Z",
    "launch_time_end": "2026-05-26T17:08:00Z",
    "launch_site": "South China Sea / northwest of Laoag",
    "launch_site_lat": 19.7,
    "launch_site_lon": 118.7,
    "launch_vehicle": null,
    "orbital_inclination": null,
    "orbital_period": null,
    "notam_ids": ["B2219/26"],
    "trajectory_zones": [
      {
        "notam_id": "B2219/26",
        "shape": "polygon",
        "vertices": [[19.7, 118.7], [19.617, 120.15], [19.0, 120.1], [19.067, 118.667]],
        "active_start": "2026-05-26T16:08:00Z",
        "active_end": "2026-05-26T17:08:00Z"
      }
    ]
  }
]

If the document contains NO relevant Q-code (QR* or QW*) AND no polygon/circle zone coordinates, return [].
"""


# ---------------------------------------------------------------------------
# Deterministic fallback parser — handles cases where the LLM returns []
# ---------------------------------------------------------------------------

def _parse_icao_time(s: str) -> str:
    """Convert YYMMDDHHMM to ISO 8601 UTC string."""
    s = s.strip()
    year = 2000 + int(s[0:2])
    month = int(s[2:4])
    day = int(s[4:6])
    hour = int(s[6:8])
    minute = int(s[8:10])
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def _parse_format_a_coord(lat_hem: str, lat_digits: str, lon_hem: str, lon_digits: str) -> tuple[float, float]:
    """Parse Format A coords: hemisphere letter then digits (N281400E1020100)."""
    # lat_digits is 6 chars DDMMSS, lon_digits is 7 chars DDDMMSS
    lat_d, lat_m, lat_s = int(lat_digits[0:2]), int(lat_digits[2:4]), int(lat_digits[4:6])
    lon_d, lon_m, lon_s = int(lon_digits[0:3]), int(lon_digits[3:5]), int(lon_digits[5:7])
    lat = lat_d + lat_m / 60.0 + lat_s / 3600.0
    lon = lon_d + lon_m / 60.0 + lon_s / 3600.0
    if lat_hem == 'S':
        lat = -lat
    if lon_hem == 'W':
        lon = -lon
    return round(lat, 4), round(lon, 4)


def _parse_format_b_coord(lat_str: str, lon_str: str) -> tuple[float, float]:
    """Parse Format B coords: digits then hemisphere (194200N 1184200E)."""
    lat_hem = lat_str[-1]
    lon_hem = lon_str[-1]
    lat_digits = lat_str[:-1]  # 6 chars DDMMSS
    lon_digits = lon_str[:-1]  # 7 chars DDDMMSS
    lat_d, lat_m, lat_s = int(lat_digits[0:2]), int(lat_digits[2:4]), int(lat_digits[4:6])
    lon_d, lon_m, lon_s = int(lon_digits[0:3]), int(lon_digits[3:5]), int(lon_digits[5:7])
    lat = lat_d + lat_m / 60.0 + lat_s / 3600.0
    lon = lon_d + lon_m / 60.0 + lon_s / 3600.0
    if lat_hem == 'S':
        lat = -lat
    if lon_hem == 'W':
        lon = -lon
    return round(lat, 4), round(lon, 4)


def _infer_location(lat: float, lon: float) -> tuple[str, float, float]:
    """Return (site_name, ref_lat, ref_lon) for known Chinese launch sites."""
    if 28 <= lat <= 29 and 101 <= lon <= 103:
        return "Xichang Satellite Launch Center", lat, lon
    if 40 <= lat <= 42 and 99 <= lon <= 101:
        return "Jiuquan Satellite Launch Center", lat, lon
    if 37 <= lat <= 39 and 111 <= lon <= 113:
        return "Taiyuan Satellite Launch Center", lat, lon
    if 19 <= lat <= 20 and 110 <= lon <= 111:
        return "Wenchang Space Launch Site", lat, lon
    return f"{lat:.2f}N {lon:.2f}E area", lat, lon


def _fallback_parse_notam(text: str) -> list[dict]:
    """Deterministic NOTAM parser — used when LLM returns empty."""
    # Must have a relevant Q-code starting with QR or QW
    q_match = re.search(r'Q\)\s*\S+/(Q[RW]\w+)/', text, re.IGNORECASE)
    if not q_match:
        return []

    # Parse NOTAM ID from first line
    id_match = re.match(r'\s*([A-Z]\d+/\d+)', text.strip())
    notam_id = id_match.group(1) if id_match else "UNKNOWN"

    # Parse B) start and C) end times
    bc_match = re.search(
        r'B\)\s*(\d{10}).*?C\)\s*(\d{10})',
        text, re.IGNORECASE | re.DOTALL
    )
    if not bc_match:
        print(f"[notam_extractor] fallback: no B/C times found in {notam_id}")
        return []

    start_iso = _parse_icao_time(bc_match.group(1))
    end_iso = _parse_icao_time(bc_match.group(2))

    vertices: list[list[float]] = []
    radius_km: float | None = None
    center: tuple[float, float] | None = None

    # Format A: N281400E1020100 — prefix hemisphere, 6+7 digits
    fmt_a_re = re.compile(r'([NS])(\d{6})([EW])(\d{7})', re.IGNORECASE)
    for m in fmt_a_re.finditer(text):
        lat, lon = _parse_format_a_coord(m.group(1).upper(), m.group(2), m.group(3).upper(), m.group(4))
        # Check if followed by a radius
        after = text[m.end():m.end() + 30]
        r_match = re.search(r'(?:radius\s+)?(\d+(?:\.\d+)?)\s*(KM|NM)', after, re.IGNORECASE)
        if r_match:
            r_val = float(r_match.group(1))
            if r_match.group(2).upper() == 'NM':
                r_val *= 1.852
            radius_km = round(r_val, 2)
            center = (lat, lon)
        else:
            vertices.append([lat, lon])

    # Format B: 194200N 1184200E — 6 digits + hemisphere, space, 7 digits + hemisphere
    if not vertices and center is None:
        fmt_b_re = re.compile(r'(\d{6}[NS])\s+(\d{7}[EW])', re.IGNORECASE)
        for m in fmt_b_re.finditer(text):
            lat, lon = _parse_format_b_coord(m.group(1).upper(), m.group(2).upper())
            vertices.append([lat, lon])

    if not vertices and center is None:
        print(f"[notam_extractor] fallback: no coordinates found in {notam_id}")
        return []

    # Infer location from first vertex or circle center
    ref_lat, ref_lon = (center if center else (vertices[0][0], vertices[0][1]))
    site_name, site_lat, site_lon = _infer_location(ref_lat, ref_lon)

    if center and radius_km:
        zone: dict = {
            "notam_id": notam_id,
            "shape": "circle",
            "center_lat": center[0],
            "center_lon": center[1],
            "radius_km": radius_km,
            "active_start": start_iso,
            "active_end": end_iso,
        }
    else:
        zone = {
            "notam_id": notam_id,
            "shape": "polygon",
            "vertices": vertices,
            "active_start": start_iso,
            "active_end": end_iso,
        }

    event = {
        "type": "launch",
        "satellite_id": None,
        "notos_id": None,
        "satellite_label": None,
        "event_date": start_iso,
        "launch_time_start": start_iso,
        "launch_time_end": end_iso,
        "launch_site": site_name,
        "launch_site_lat": site_lat,
        "launch_site_lon": site_lon,
        "launch_vehicle": None,
        "orbital_inclination": None,
        "orbital_period": None,
        "notam_ids": [notam_id],
        "trajectory_zones": [zone],
    }
    print(f"[notam_extractor] fallback parsed {notam_id}: {zone['shape']} zone, {len(vertices)} vertices")
    return [event]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def extract_launch_events(text: str, source_meta: dict) -> list[dict]:
    """Extract launch events from NOTOS/NOTAM report text. Returns list of event dicts."""
    client = _get_client()

    text_excerpt = text[:40000]

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract all relevant QR*/QW* restricted/danger area events from the following NOTAM text:\n\n{text_excerpt}"},
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
            print(f"[notam_extractor] unexpected response shape: {type(events)}")
            events = []
        valid = [e for e in events if isinstance(e, dict) and e.get("type") == "launch"]
        print(f"[notam_extractor] LLM extracted {len(valid)} launch events ({len(events) - len(valid)} invalid dropped)")
    except json.JSONDecodeError as exc:
        print(f"[notam_extractor] JSON parse error: {exc}\nRaw: {raw[:500]}")
        valid = []

    # If LLM returned nothing, try deterministic fallback
    if not valid:
        print("[notam_extractor] LLM returned no events — trying regex fallback")
        valid = _fallback_parse_notam(text)

    # Normalise trajectory_zone vertices: LLM may return {lat, lon} objects instead of [lat, lon] arrays
    for ev in valid:
        for zone in (ev.get("trajectory_zones") or []):
            if isinstance(zone.get("vertices"), list):
                zone["vertices"] = [
                    [v["lat"], v["lon"]] if isinstance(v, dict) else v
                    for v in zone["vertices"]
                ]

    return valid
