"""
StudentApp Pool Reservation Parser and Client.
Supports parsing HTTP Archive (.har) export files or querying the StudentApp sports API directly.
"""
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

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
    """
    Retrieves pool bookings from a live student sports API (supporting direct email/password login),
    token caching, or an optional offline HAR file export.
    """

    def __init__(self, config: StudentAppConfig):
        self.config = config
        self.token_path = Path(self.config.token_file)

    def is_configured(self) -> bool:
        """Check if StudentApp credentials, tokens, or files are configured."""
        return self.config.is_configured

    def _load_cached_token_data(self) -> Optional[Dict[str, Any]]:
        """Load stored token data from token file if present and valid."""
        if not self.token_path.is_file():
            return None
        try:
            with open(self.token_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception as err:
            logger.warning("Could not read StudentApp token file: %s", err)
            return None

    def _save_token_data(self, data: Dict[str, Any]) -> None:
        """Save token data to token file."""
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as err:
            logger.warning("Could not save StudentApp token file: %s", err)

    def get_valid_token(self) -> Optional[str]:
        """Get an existing valid Bearer token or authenticate with email/password."""
        if self.config.api_token:
            return self.config.api_token

        cached = self._load_cached_token_data()
        if cached and "access_token" in cached and cached["access_token"]:
            expires_at = cached.get("expires_at")
            if expires_at is None or expires_at > time.time() + 60:
                return cached["access_token"]

        # Attempt login if credentials are provided
        if self.config.email and self.config.password:
            ok, _ = self.login()
            if ok:
                fresh = self._load_cached_token_data()
                if fresh and "access_token" in fresh and fresh["access_token"]:
                    return fresh["access_token"]

        return None

    def get_cached_cookies(self) -> Dict[str, str]:
        """Get any cached session cookies."""
        cached = self._load_cached_token_data()
        if cached and isinstance(cached.get("cookies"), dict):
            return cached["cookies"]
        return {}

    def get_login_endpoint(self) -> Optional[str]:
        """Resolve the login endpoint URL."""
        if self.config.login_url:
            return self.config.login_url
        if self.config.api_url:
            base = self.config.api_url.rstrip("/")
            if "/reservations" in base:
                return base.replace("/reservations", "/auth/login")
            if "/bookings" in base:
                return base.replace("/bookings", "/auth/login")
            return f"{base}/auth/login"
        return None

    def login(self) -> Tuple[bool, str]:
        """Authenticate using email and password, caching the resulting token/cookies."""
        if not (self.config.email and self.config.password):
            return False, "StudentApp email or password not provided (set STUDENTAPP_EMAIL and STUDENTAPP_PASSWORD in .env)."

        login_url = self.get_login_endpoint()
        if not login_url:
            return False, "Cannot determine StudentApp login endpoint (set STUDENTAPP_LOGIN_URL or STUDENTAPP_API_URL in .env)."

        payload = {
            "email": self.config.email,
            "username": self.config.email,
            "password": self.config.password,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TrainingPeaksSync/2.0 (Mauro Edition)",
        }

        try:
            logger.info("Authenticating to StudentApp at: %s", login_url)
            session = requests.Session()
            resp = session.post(login_url, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()

            token = ""
            expires_at = None
            token_data: Dict[str, Any] = {}

            try:
                data = resp.json()
                token_data = data if isinstance(data, dict) else {}
                for k in ["access_token", "token", "jwt", "bearer", "id_token"]:
                    if k in token_data and isinstance(token_data[k], str):
                        token = token_data[k]
                        break
                if not token and isinstance(token_data.get("data"), dict):
                    inner = token_data["data"]
                    for k in ["access_token", "token", "jwt"]:
                        if k in inner and isinstance(inner[k], str):
                            token = inner[k]
                            break

                expires_in = token_data.get("expires_in")
                if isinstance(expires_in, (int, float)):
                    expires_at = time.time() + expires_in
            except Exception:
                pass

            cookies = session.cookies.get_dict()

            save_payload = {
                "email": self.config.email,
                "access_token": token,
                "expires_at": expires_at,
                "cookies": cookies,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save_token_data(save_payload)
            logger.info("StudentApp login successful for %s (session cached).", self.config.email)
            return True, f"Successfully logged into StudentApp as '{self.config.email}'."
        except Exception as err:
            logger.error("StudentApp login failed: %s", err)
            return False, f"StudentApp login failed: {err}"

    def test_connection(self) -> Tuple[bool, str]:
        """Test connection and authentication to StudentApp."""
        if not self.is_configured():
            return False, "StudentApp is not configured (set STUDENTAPP_EMAIL and STUDENTAPP_PASSWORD in .env)."

        # 1. If HAR file exists
        if self.config.har_path and self.config.har_path.is_file():
            bookings = StudentAppParser.parse_har_file(self.config.har_path)
            return True, f"HAR file verified: found {len(bookings)} booking(s)."

        # 2. If email/password configured
        if self.config.email and self.config.password:
            login_url = self.get_login_endpoint()
            if not login_url and not self.config.api_url:
                return False, "STUDENTAPP_EMAIL is configured, but STUDENTAPP_API_URL or STUDENTAPP_LOGIN_URL is missing in .env."
            ok, msg = self.login()
            return ok, msg

        # 3. If explicit API token
        if self.config.api_url and self.config.api_token:
            return True, f"StudentApp API token configured for {self.config.api_url}."

        # 4. If cached token exists
        cached = self._load_cached_token_data()
        if cached and (cached.get("access_token") or cached.get("cookies")):
            return True, f"StudentApp cached session active for '{cached.get('email', 'athlete')}'."

        return False, "StudentApp configuration is incomplete."

    def fetch_reservations(self) -> List[SwimReservation]:
        """Fetch reservations from HAR file or live API endpoint."""
        reservations: List[SwimReservation] = []

        # 1. Parse from HAR file if configured
        if self.config.har_path:
            reservations.extend(StudentAppParser.parse_har_file(self.config.har_path))

        # 2. Live API query if endpoint is configured
        if self.config.api_url:
            api_reservations = self._fetch_from_api()
            reservations.extend(api_reservations)

        # Deduplicate by reservation_id
        seen_ids = set()
        unique: List[SwimReservation] = []
        for r in reservations:
            if r.reservation_id not in seen_ids:
                seen_ids.add(r.reservation_id)
                unique.append(r)

        return unique

    def _fetch_from_api(self) -> List[SwimReservation]:
        """Query live StudentApp API for reservations using cached or authenticated session."""
        token = self.get_valid_token()
        cookies = self.get_cached_cookies()

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TrainingPeaksSync/2.0 (Mauro Edition)",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            logger.info("Querying StudentApp API: %s", self.config.api_url)
            resp = requests.get(self.config.api_url, headers=headers, cookies=cookies, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            return StudentAppParser.extract_from_payload(payload, url=self.config.api_url)
        except Exception as err:
            logger.error("Failed to query StudentApp API: %s", err)
            return []
