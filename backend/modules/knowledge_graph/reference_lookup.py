"""
ReferenceLookup: enriches satellite nodes with data from the UCS satellite database CSV.
Called during ingest to fill missing attributes before a node goes to the pending queue.
"""
import csv
import pathlib
import re
from typing import Optional

REFERENCE_DIR = pathlib.Path(__file__).parents[3] / "data" / "reference"

# CSV column → KG attribute mapping
_COL_MAP = {
    "NORAD Number":              "norad_id",
    "Date of Launch":            "launch_date",
    "Operator/Owner":            "operator",
    "Country of Operator/Owner": "operator_country",
    "Contractor":                "manufacturer",
    "Class of Orbit":            "orbit_type",
    "Inclination (degrees)":     "inclination_deg",
    "Launch Vehicle":            "launch_vehicle_name",
}


def _normalize(name: str) -> str:
    """Lowercase, strip punctuation/whitespace for fuzzy matching."""
    return re.sub(r"[\s\-_.,()]+", " ", name.lower()).strip()


def _mission_from_row(row: dict) -> str:
    purpose = row.get("Purpose", "").strip()
    detail = row.get("Detailed Purpose", "").strip()
    if detail and detail != purpose:
        return f"{purpose} — {detail}"
    return purpose


def _altitude_from_row(row: dict) -> Optional[float]:
    try:
        perigee = float(row.get("Perigee (km)", "") or 0)
        apogee = float(row.get("Apogee (km)", "") or 0)
        if perigee > 0 and apogee > 0:
            return round((perigee + apogee) / 2, 1)
    except (ValueError, TypeError):
        pass
    return None


class ReferenceLookup:
    def __init__(self):
        # norad_id (str) → row dict
        self._by_norad: dict[str, dict] = {}
        # normalized name → row dict (first match wins)
        self._by_name: dict[str, dict] = {}
        self._loaded = False

    def load(self) -> None:
        csv_files = list(REFERENCE_DIR.glob("*.csv"))
        if not csv_files:
            print("[reference] No CSV files found in data/reference/ — skipping")
            return
        total = 0
        for csv_path in csv_files:
            try:
                with open(csv_path, encoding="utf-8-sig", errors="replace") as f:
                    for row in csv.DictReader(f):
                        norad = (row.get("NORAD Number") or "").strip()
                        if norad:
                            self._by_norad[norad] = row

                        for name_col in ("Current Official Name of Satellite",
                                         "Name of Satellite, Alternate Names"):
                            raw = row.get(name_col, "") or ""
                            for part in raw.split(","):
                                key = _normalize(part)
                                if key and key not in self._by_name:
                                    self._by_name[key] = row
                        total += 1
            except Exception as e:
                print(f"[reference] Failed to load {csv_path.name}: {e}")
        self._loaded = True
        print(f"[reference] Loaded {total} rows, {len(self._by_norad)} NORAD IDs indexed")

    def lookup(self, label: str = "", norad_id: str = "") -> Optional[dict]:
        """Return raw CSV row matching by NORAD ID first, then by name."""
        if norad_id:
            row = self._by_norad.get(str(norad_id).strip())
            if row:
                return row
        if label:
            key = _normalize(label)
            # Exact match
            if key in self._by_name:
                return self._by_name[key]
            # Partial match: find the best overlap
            best, best_score = None, 0
            for indexed_key, row in self._by_name.items():
                # score = length of longest common substring / max length
                common = len(set(key.split()) & set(indexed_key.split()))
                if common > best_score:
                    best_score = common
                    best = row
            if best_score >= 2:  # at least 2 words in common
                return best
        return None

    def enrich(self, label: str, current_attrs: dict, norad_id: str = "") -> dict:
        """
        Returns a dict of {attr_key: value} for attributes that are currently null/missing.
        Only fills fields where current value is None or missing.
        """
        row = self.lookup(label=label, norad_id=norad_id)
        if not row:
            return {}

        fills = {}

        for col, attr_key in _COL_MAP.items():
            cur = current_attrs.get(attr_key)
            cur_val = cur.get("value") if isinstance(cur, dict) else cur
            if cur_val is not None and cur_val != "":
                continue  # already filled
            val = (row.get(col) or "").strip()
            if val and val not in ("0", "NR", "N/A", "NA"):
                fills[attr_key] = val

        # mission: build from Purpose + Detailed Purpose
        cur_mission = current_attrs.get("mission")
        if not (cur_mission.get("value") if isinstance(cur_mission, dict) else cur_mission):
            mission = _mission_from_row(row)
            if mission:
                fills["mission"] = mission

        # altitude_km
        cur_alt = current_attrs.get("altitude_km")
        if not (cur_alt.get("value") if isinstance(cur_alt, dict) else cur_alt):
            alt = _altitude_from_row(row)
            if alt:
                fills["altitude_km"] = alt

        return fills


reference_lookup = ReferenceLookup()
