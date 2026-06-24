"""Conjunction data cache with 8-hour TTL respecting Space-Track API limits."""
import json
import pathlib
import threading
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

CACHE_FILE = pathlib.Path(__file__).parents[3] / "data" / "conjunctions" / "cdm_cache.json"
CACHE_TTL_HOURS = 8


class ConjunctionCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = None

    def _load(self):
        """Load cache from disk."""
        if self._data is not None:
            return
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if CACHE_FILE.exists():
            try:
                self._data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load CDM cache: {e}")
                self._data = {"cdms": [], "last_updated": None}
        else:
            self._data = {"cdms": [], "last_updated": None}

    def _save(self):
        """Save cache to disk."""
        if self._data is None:
            return
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def needs_refresh(self) -> bool:
        """Check if cache needs refresh (older than TTL_HOURS)."""
        with self._lock:
            self._load()
            last_updated = self._data.get("last_updated")
            if not last_updated:
                return True  # Never updated
            try:
                last_dt = datetime.fromisoformat(last_updated).replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - last_dt
                return age > timedelta(hours=CACHE_TTL_HOURS)
            except (ValueError, TypeError):
                return True

    def update(self, cdms: list[dict]) -> None:
        """Update cache with fresh CDM list."""
        with self._lock:
            self._load()
            self._data["cdms"] = cdms
            self._data["last_updated"] = datetime.now(timezone.utc).isoformat()
            self._save()
            logger.info(f"CDM cache updated: {len(cdms)} records")

    def get_conjunctions_for_satellite(
        self, norad_id: str, days: int = 30, min_distance_km: float = 100.0
    ) -> list[dict]:
        """Query cached CDMs for a satellite.

        Shows conjunctions from the past N days to future N days (centered on now).
        This allows viewing both recent history and near-term predictions.
        """
        with self._lock:
            self._load()
            cdms = self._data.get("cdms", [])

        now = datetime.now(timezone.utc)
        past_cutoff = now - timedelta(days=days)  # Past N days
        future_cutoff = now + timedelta(days=days)  # Future N days
        results = []

        for cdm in cdms:
            # Match satellite
            if str(cdm.get("norad_id_1", "")) != norad_id and str(cdm.get("norad_id_2", "")) != norad_id:
                continue

            # Filter by distance
            if float(cdm.get("min_distance_km", float("inf"))) > min_distance_km:
                continue

            # Filter by date (past and future)
            try:
                tca = datetime.fromisoformat(cdm.get("tca", "").replace("Z", "+00:00"))
                if tca < past_cutoff or tca > future_cutoff:
                    continue
            except (ValueError, TypeError):
                continue

            results.append(cdm)

        return sorted(results, key=lambda x: x.get("tca", ""), reverse=True)  # Newest first

    def last_updated(self) -> str | None:
        """Return human-readable last update time."""
        with self._lock:
            self._load()
            return self._data.get("last_updated")


conjunction_cache = ConjunctionCache()
