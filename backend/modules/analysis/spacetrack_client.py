"""Space-Track.org API client for conjunction data retrieval."""
import os
import logging
import json
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Raw data storage
RAW_DATA_DIR = pathlib.Path(__file__).parents[3] / "data" / "spacetrack_raw"


def _save_raw_response(data: list, norad_id: Optional[str] = None) -> None:
    """Save raw Space-Track API response to disk."""
    try:
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Filename: cdm_raw_YYYY-MM-DD_HH-MM-SS_[NORAD_ID].json
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        suffix = f"_{norad_id}" if norad_id else "_all"
        filename = f"cdm_raw_{timestamp}{suffix}.json"
        filepath = RAW_DATA_DIR / filename

        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Raw Space-Track response saved: {filename} ({len(data)} records)")
    except Exception as e:
        logger.warning(f"Failed to save raw response: {e}")


class SpaceTrackClient:
    """Client for Space-Track.org CDM (Conjunction Data Message) API."""

    def __init__(self):
        self.username = os.environ.get("SPACETRACK_USERNAME", "").strip()
        self.password = os.environ.get("SPACETRACK_PASSWORD", "").strip()
        self.session = None

    def _get_session(self):
        """Initialize and authenticate session with Space-Track."""
        if self.session is None:
            import requests

            if not self.username or not self.password:
                logger.error("Space-Track credentials not configured in .env")
                return None

            self.session = requests.Session()

            try:
                # Login to Space-Track
                logger.info(f"Logging into Space-Track as {self.username}")
                login_url = "https://www.space-track.org/ajaxauth/login"
                login_data = {
                    "identity": self.username,
                    "password": self.password,
                }

                resp = self.session.post(login_url, data=login_data, timeout=10)
                logger.info(f"Login response: {resp.status_code}")

                if resp.status_code != 200:
                    logger.error(f"Space-Track login failed: {resp.status_code}")
                    self.session = None
                    return None

                logger.info("Space-Track authentication successful")

            except Exception as e:
                logger.error(f"Space-Track login error: {type(e).__name__}: {e}")
                self.session = None
                return None

        return self.session

    def get_conjunctions(
        self,
        norad_id: Optional[str] = None,
        days_ahead: int = 30,
        min_distance_km: float = 100.0,
    ) -> Optional[list[dict]]:
        """
        Fetch conjunction warnings for a satellite or ALL satellites.

        Args:
            norad_id: NORAD catalog number (string or int), or None to fetch ALL CDMs
            days_ahead: Look ahead N days (default 30)
            min_distance_km: Filter to events <= this distance (0 = no filter on fetch)

        Returns:
            List of conjunction events or None on error
        """
        session = self._get_session()
        if not session:
            logger.warning("Space-Track session not available")
            return None

        try:
            if norad_id is not None:
                norad_id = str(norad_id)
                logger.debug(f"Fetching conjunctions for NORAD {norad_id}")
            else:
                logger.debug("Fetching ALL conjunctions (cache refresh)")

            # Query cdm_public for future conjunction predictions
            # Filter by TCA (Time of Closest Approach) in the next 30 days
            now = datetime.now(timezone.utc)
            future = now + timedelta(days=days_ahead)
            start_date = now.strftime("%Y-%m-%d")
            end_date = future.strftime("%Y-%m-%d")

            url = (
                "https://www.space-track.org/basicspacedata/query"
                "/class/cdm_public"
                f"/TCA/{start_date}--{end_date}"  # Date range format
                "/orderby/TCA%20asc"
                "/limit/500"
                "/format/json"
            )

            logger.debug(f"Querying CDM public API")
            resp = session.get(url, timeout=30)
            logger.info(f"Query response: {resp.status_code}")

            if resp.status_code == 401:
                logger.error("Space-Track: Unauthorized (401)")
                self.session = None
                return None
            elif resp.status_code == 403:
                logger.error("Space-Track: Forbidden (403)")
                return None
            elif resp.status_code != 200:
                logger.error(f"Space-Track: HTTP {resp.status_code}")
                return None

            results = resp.json()

            # Save raw API response
            _save_raw_response(results, norad_id)

            if not results:
                logger.debug(f"No conjunctions found for NORAD {norad_id}")
                return []

            # Parse and filter results
            conjunctions = []
            now = datetime.now(timezone.utc)
            cutoff_date = now + timedelta(days=days_ahead)

            for cdm in results:
                try:
                    # Check if either satellite matches our norad_id (or fetch all if norad_id is None)
                    sat1_id = str(cdm.get("SAT_1_ID", "")).strip()
                    sat2_id = str(cdm.get("SAT_2_ID", "")).strip()

                    # Skip if norad_id specified and neither satellite matches
                    if norad_id is not None and sat1_id != norad_id and sat2_id != norad_id:
                        continue

                    # Parse TCA (Time of Closest Approach)
                    tca_str = cdm.get("TCA", "")
                    if not tca_str:
                        continue

                    # Parse ISO format datetime
                    try:
                        # Handle both "2026-06-04T12:31:36.882000Z" and "2026-06-04T12:31:36.882000"
                        tca_clean = tca_str.rstrip("Z")
                        tca = datetime.fromisoformat(tca_clean)
                        # If no timezone info, assume UTC
                        if tca.tzinfo is None:
                            tca = tca.replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError):
                        logger.debug(f"Could not parse TCA: {tca_str}")
                        continue

                    # Filter by date range (only when querying specific satellite, not for cache refresh)
                    if norad_id is not None and (tca < now or tca > cutoff_date):
                        continue

                    # Get minimum range in km
                    min_dist_str = str(cdm.get("MIN_RNG", "")).strip()
                    try:
                        min_dist = float(min_dist_str) if min_dist_str else float("inf")
                    except (ValueError, TypeError):
                        logger.debug(f"Could not parse MIN_RNG: {min_dist_str}")
                        continue

                    # Filter by minimum distance (skip if min_distance_km=0, meaning cache refresh)
                    if min_distance_km > 0 and min_dist > min_distance_km:
                        continue

                    # Build record with both satellite names
                    record = {
                        "norad_id_1": sat1_id,
                        "norad_id_2": sat2_id,
                        "name_1": cdm.get("SAT_1_NAME", f"NORAD {sat1_id}"),
                        "name_2": cdm.get("SAT_2_NAME", f"NORAD {sat2_id}"),
                        "tca": tca.isoformat(),
                        "min_distance_km": min_dist,
                        "probability": float(cdm.get("PROBABILITY_OF_COLLISION", 0)) if cdm.get("PROBABILITY_OF_COLLISION") else None,
                        "source": "space-track.org (cdm_public)",
                        "_cdm_id": cdm.get("CDM_ID"),
                        "_created": cdm.get("CREATED"),
                    }

                    # Add "other" satellite field for queries with specific satellite
                    if norad_id is not None:
                        if sat1_id == norad_id:
                            record["norad_id_other"] = sat2_id
                            record["name_other"] = cdm.get("SAT_2_NAME", f"NORAD {sat2_id}")
                        else:
                            record["norad_id_other"] = sat1_id
                            record["name_other"] = cdm.get("SAT_1_NAME", f"NORAD {sat1_id}")

                    conjunctions.append(record)

                except (ValueError, KeyError, TypeError) as e:
                    logger.debug(f"Error parsing CDM: {e}")
                    continue

            # Deduplicate: keep only the latest version of each conjunction
            # Group by sorted satellite pair + TCA (order-independent), keep latest CREATED
            deduped = {}
            for conj in conjunctions:
                # Use sorted satellite IDs so order doesn't matter
                sat_pair = tuple(sorted([conj["norad_id_1"], conj["norad_id_2"]]))
                key = (sat_pair, conj["tca"])
                if key not in deduped or (conj.get("_created") or "") > (deduped[key].get("_created") or ""):
                    deduped[key] = conj

            # Remove internal fields before returning
            result = []
            for conj in deduped.values():
                conj_clean = {k: v for k, v in conj.items() if not k.startswith("_")}
                result.append(conj_clean)

            logger.info(f"Retrieved {len(result)} conjunctions for NORAD {norad_id} (deduped from {len(conjunctions)})")
            return result

        except Exception as e:
            logger.error(f"Space-Track query error: {type(e).__name__}: {e}")
            return None


_client = None


def get_spacetrack_client() -> SpaceTrackClient:
    """Get singleton Space-Track client."""
    global _client
    if _client is None:
        _client = SpaceTrackClient()
    return _client
