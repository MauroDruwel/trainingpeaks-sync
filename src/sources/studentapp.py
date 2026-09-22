"""
StudentApp Pool Reservation Parser and Client.
Supports parsing HTTP Archive (.har) export files or querying the StudentApp sports API directly.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests

from ..config import StudentAppConfig
from ..models import SwimReservation


logger = logging.getLogger(__name__)


class StudentAppParser:
    """Parses StudentApp reservations from HAR file responses or API payloads."""

    @classmethod
    def parse_har_file(cls, har_path: Path) -> List[SwimReservation]:
        """Parse a .har file, scanning for booking/reservation endpoints and payloads."""
        reservations: List[SwimReservation] = []
        if not har_path.is_file():
            logger.warning("HAR file does not exist: %s", har_path)
            return reservations

        try:
            with open(har_path, "r", encoding="utf-8") as f:
                har_data = json.load(f)

            entries = har_data.get("log", {}).get("entries", [])
            logger.info("Scanning %d HTTP requests in HAR file: %s", len(entries), har_path.name)

            for entry in entries:
                request_url = entry.get("request", {}).get("url", "")
                response = entry.get("response", {})
                content = response.get("content", {})
                mime_type = content.get("mimeType", "")
                text = content.get("text", "")

                if not text or "json" not in mime_type:
                    continue

                # Filter for likely reservation endpoints
                is_candidate_endpoint = any(
                    term in request_url.lower()
                    for term in ["reservation", "booking", "activit", "sport", "inschrijving", "zwem", "pool"]
                )

                try:
                    payload = json.loads(text)
                    extracted = cls.extract_from_payload(payload, url=request_url)
                    reservations.extend(extracted)
                except Exception:
                    continue

            # Deduplicate by reservation_id
            seen_ids = set()
            unique_reservations = []
            for r in reservations:
                if r.reservation_id not in seen_ids:
                    seen_ids.add(r.reservation_id)
                    unique_reservations.append(r)

            logger.info("Extracted %d unique StudentApp reservations from HAR file.", len(unique_reservations))
            return unique_reservations

        except Exception as err:
            logger.error("Failed to parse HAR file %s: %s", har_path, err)
            return []

    @classmethod
    def extract_from_payload(cls, data: Any, url: str = "") -> List[SwimReservation]:
        """Recursively scan JSON payload for swim reservation structures."""
        results: List[SwimReservation] = []

        if isinstance(data, list):
            for item in data:
                results.extend(cls.extract_from_payload(item, url=url))
        elif isinstance(data, dict):
            # Check if this dictionary represents a reservation
            reservation = cls._parse_single_dict(data, url=url)
            if reservation:
                results.append(reservation)
            else:
                # Check nested values (e.g. data["items"], data["reservations"], data["data"])
                for k, v in data.items():
                    if isinstance(v, (list, dict)):
                        results.extend(cls.extract_from_payload(v, url=url))

        return results

    @classmethod
    def _parse_single_dict(cls, d: Dict[str, Any], url: str = "") -> Optional[SwimReservation]:
        """Attempt to construct a SwimReservation from a single JSON dictionary."""
        # Find sports/activity title
        name_keys = ["title", "name", "activity", "sport", "description", "course_name"]
        activity_name = ""
        for k in name_keys:
            if k in d and isinstance(d[k], str):
                activity_name = d[k]
                break

        # Check if activity relates to swimming or pool
        is_swim = any(
            term in activity_name.lower() or term in url.lower()
            for term in ["zwem", "swim", "sportbad", "baantjes", "pool", "aquatics", "gusb"]
        )

        if not is_swim and not ("facility" in d and "zwem" in str(d["facility"]).lower()):
            return None

        # Extract dates / times
        start_dt = cls._parse_datetime(d, ["start", "start_time", "starts_at", "begin", "from", "date", "datum"])
        if not start_dt:
            return None

        end_dt = cls._parse_datetime(d, ["end", "end_time", "ends_at", "eind", "to", "until"])
        duration = int((end_dt - start_dt).total_seconds()) if end_dt else 3600

        # Identifier
        res_id = str(d.get("id") or d.get("booking_id") or d.get("reservation_id") or f"studentapp_{start_dt.strftime('%Y%m%d_%H%M')}")

        facility = str(d.get("facility") or d.get("location") or d.get("room") or "Student Sports Pool (GUSB)")

        return SwimReservation(
            source="studentapp",
            reservation_id=res_id,
            title=f"StudentApp Swim ({activity_name or facility})",
            facility=facility,
            start_time=start_dt,
            end_time=end_dt,
            duration_seconds=duration,
            raw_details=d,
        )

    @classmethod
    def _parse_datetime(cls, d: Dict[str, Any], candidate_keys: List[str]) -> Optional[datetime]:
        """Try candidate keys to extract a UTC datetime object."""
        for key in candidate_keys:
            if key not in d or not d[key]:
                continue
            val = d[key]
            if isinstance(val, (int, float)):
                # Unix timestamp (seconds or ms)
                ts = val if val < 10**11 else val / 1000
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(val, str):
                # ISO 8601 or standard string
                try:
                    clean = val.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(clean)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    pass
        return None


class StudentAppClient:
    """Retrieves pool bookings from a configured HAR file or live student sports API."""

    def __init__(self, config: StudentAppConfig):
        self.config = config

    def fetch_reservations(self) -> List[SwimReservation]:
        """Fetch reservations from HAR file or live API endpoint."""
        reservations: List[SwimReservation] = []

        # 1. Parse from HAR file if configured
        if self.config.har_path:
            reservations.extend(StudentAppParser.parse_har_file(self.config.har_path))

        # 2. Live API query if endpoint and token are configured
        if self.config.api_url and self.config.api_token:
            api_reservations = self._fetch_from_api()
            reservations.extend(api_reservations)

        return reservations

    def _fetch_from_api(self) -> List[SwimReservation]:
        """Query live StudentApp API for reservations."""
        headers = {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
            "User-Agent": "TrainingPeaksSync/2.0 (Mauro Edition)",
        }
        try:
            logger.info("Querying StudentApp API: %s", self.config.api_url)
            resp = requests.get(self.config.api_url, headers=headers, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            return StudentAppParser.extract_from_payload(payload, url=self.config.api_url)
        except Exception as err:
            logger.error("Failed to query StudentApp API: %s", err)
            return []
