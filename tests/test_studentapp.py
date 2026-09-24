"""
Unit tests for StudentApp HAR parser and API client.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.config import StudentAppConfig
from src.sources.studentapp import StudentAppParser, StudentAppClient


class TestStudentAppParser(unittest.TestCase):
    """Test parsing HAR file exports and API JSON payloads."""

    def test_parse_har_file_with_swim_booking(self):
        har_content = {
            "log": {
                "version": "1.2",
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": "https://sports.university.be/api/v1/user/reservations",
                        },
                        "response": {
                            "status": 200,
                            "content": {
                                "mimeType": "application/json",
                                "text": json.dumps({
                                    "status": "success",
                                    "reservations": [
                                        {
                                            "id": "STUD-BOOK-42",
                                            "activity": "Baantjeszwemmen GUSB",
                                            "facility": "GUSB Zwembad Gent",
                                            "starts_at": "2026-09-23T07:00:00Z",
                                            "ends_at": "2026-09-23T08:30:00Z",
                                            "status": "CONFIRMED"
                                        },
                                        {
                                            "id": "NON-SWIM-1",
                                            "activity": "Fitness Zaal",
                                            "starts_at": "2026-09-24T14:00:00Z"
                                        }
                                    ]
                                })
                            }
                        }
                    }
                ]
            }
        }

        with tempfile.NamedTemporaryFile(suffix=".har", mode="w", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(har_content, tmp)

        try:
            bookings = StudentAppParser.parse_har_file(tmp_path)
            self.assertEqual(len(bookings), 1)
            self.assertEqual(bookings[0].source, "studentapp")
            self.assertEqual(bookings[0].reservation_id, "STUD-BOOK-42")
            self.assertEqual(bookings[0].facility, "GUSB Zwembad Gent")
            self.assertEqual(bookings[0].duration_seconds, 5400)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_parse_non_existent_har(self):
        bookings = StudentAppParser.parse_har_file(Path("/non/existent/path.har"))
        self.assertEqual(bookings, [])


class TestStudentAppClient(unittest.TestCase):
    """Test StudentAppClient with HAR file and live API."""

    def test_client_fetch_via_api(self):
        config = StudentAppConfig(
            api_url="https://api.example.com/bookings",
            api_token="test-token"
        )
        client = StudentAppClient(config)

        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "id": "API-SWIM-101",
                "sport": "Zwemmen",
                "facility": "Zwembad GUSB",
                "start": "2026-09-25T07:00:00Z",
                "end": "2026-09-25T08:00:00Z"
            }
        ]
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            reservations = client.fetch_reservations()
            self.assertEqual(len(reservations), 1)
            self.assertEqual(reservations[0].reservation_id, "API-SWIM-101")

    def test_login_success(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            config = StudentAppConfig(
                email="student@ugent.be",
                password="secretpassword",
                login_url="https://sports.university.be/api/v1/auth/login",
                token_file=str(tmp_path),
            )
            client = StudentAppClient(config)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "access_token": "bearer-jwt-xyz-123",
                "expires_in": 3600,
            }
            mock_resp.raise_for_status.return_value = None

            with patch("requests.Session.post", return_value=mock_resp):
                ok, msg = client.login()
                self.assertTrue(ok)
                self.assertIn("student@ugent.be", msg)

            # Verify token file was written
            with open(tmp_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["access_token"], "bearer-jwt-xyz-123")
            self.assertEqual(saved["email"], "student@ugent.be")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_login_failure(self):
        config = StudentAppConfig(
            email="student@ugent.be",
            password="wrongpassword",
            login_url="https://sports.university.be/api/v1/auth/login",
        )
        client = StudentAppClient(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = Exception("HTTP 401 Unauthorized")

        with patch("requests.Session.post", return_value=mock_resp):
            ok, msg = client.login()
            self.assertFalse(ok)
            self.assertIn("StudentApp login failed", msg)

    def test_login_missing_credentials(self):
        config = StudentAppConfig()
        client = StudentAppClient(config)
        ok, msg = client.login()
        self.assertFalse(ok)
        self.assertIn("not provided", msg)

    def test_get_valid_token_uses_cached(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            json.dump({
                "access_token": "cached-valid-token",
                "expires_at": 9999999999,
            }, tmp)

        try:
            config = StudentAppConfig(
                email="student@ugent.be",
                password="secretpassword",
                token_file=str(tmp_path),
            )
            client = StudentAppClient(config)
            token = client.get_valid_token()
            self.assertEqual(token, "cached-valid-token")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_get_valid_token_expired_triggers_login(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            json.dump({
                "access_token": "old-expired-token",
                "expires_at": 100,  # Expired long ago
            }, tmp)

        try:
            config = StudentAppConfig(
                email="student@ugent.be",
                password="secretpassword",
                login_url="https://sports.university.be/api/v1/auth/login",
                token_file=str(tmp_path),
            )
            client = StudentAppClient(config)

            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "access_token": "fresh-token-789",
                "expires_in": 3600,
            }
            mock_resp.raise_for_status.return_value = None

            with patch("requests.Session.post", return_value=mock_resp):
                token = client.get_valid_token()
                self.assertEqual(token, "fresh-token-789")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_test_connection_not_configured(self):
        config = StudentAppConfig()
        client = StudentAppClient(config)
        ok, msg = client.test_connection()
        self.assertFalse(ok)
        self.assertIn("not configured", msg)

    def test_test_connection_email_pw_success(self):
        config = StudentAppConfig(
            email="student@ugent.be",
            password="secretpassword",
            login_url="https://sports.university.be/api/v1/auth/login",
            token_file=".tmp_tokens_test.json",
        )
        client = StudentAppClient(config)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "tok"}
        mock_resp.raise_for_status.return_value = None

        with patch("requests.Session.post", return_value=mock_resp):
            ok, msg = client.test_connection()
            self.assertTrue(ok)
            self.assertIn("Successfully logged into StudentApp", msg)

        tmp_p = Path(".tmp_tokens_test.json")
        if tmp_p.exists():
            tmp_p.unlink()

    def test_test_connection_missing_login_endpoint(self):
        config = StudentAppConfig(
            email="student@ugent.be",
            password="secretpassword",
            token_file=".tmp_tokens_missing.json",
        )
        client = StudentAppClient(config)
        ok, msg = client.test_connection()
        self.assertFalse(ok)
        self.assertIn("STUDENTAPP_API_URL or STUDENTAPP_LOGIN_URL is missing", msg)

    def test_fetch_reservations_with_email_login(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            config = StudentAppConfig(
                email="student@ugent.be",
                password="secretpassword",
                api_url="https://sports.university.be/api/v1/user/reservations",
                token_file=str(tmp_path),
            )
            client = StudentAppClient(config)

            mock_login_resp = MagicMock()
            mock_login_resp.json.return_value = {"access_token": "live-tok-123"}
            mock_login_resp.raise_for_status.return_value = None

            mock_get_resp = MagicMock()
            mock_get_resp.json.return_value = [
                {
                    "id": "LIVE-BOOK-99",
                    "sport": "Baantjeszwemmen",
                    "facility": "GUSB Zwembad",
                    "start": "2026-09-24T18:00:00Z",
                    "end": "2026-09-24T19:30:00Z",
                }
            ]
            mock_get_resp.raise_for_status.return_value = None

            with patch("requests.Session.post", return_value=mock_login_resp), \
                 patch("requests.get", return_value=mock_get_resp):
                reservations = client.fetch_reservations()
                self.assertEqual(len(reservations), 1)
                self.assertEqual(reservations[0].reservation_id, "LIVE-BOOK-99")
                self.assertEqual(reservations[0].facility, "GUSB Zwembad")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
