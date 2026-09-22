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
