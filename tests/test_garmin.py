"""
Unit tests for Garmin Connect uploader.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import GarminConfig
from src.garmin.client import GarminUploader


class TestGarminUploader(unittest.TestCase):
    """Test Garmin Connect activity uploader and bridge."""

    def test_is_configured(self):
        cfg = GarminConfig(token_file="/non/existent/tokens.json")
        uploader = GarminUploader(cfg)
        self.assertFalse(uploader.is_configured())

        cfg.email = "mauro@example.com"
        cfg.password = "password"
        self.assertTrue(uploader.is_configured())

    def test_upload_tcx_file_not_found(self):
        cfg = GarminConfig(email="user@example.com", password="pwd", token_file="/non/existent/tokens.json")
        uploader = GarminUploader(cfg)
        result = uploader.upload_tcx(Path("/non/existent/activity.tcx"))
        self.assertFalse(result)

    def test_test_connection_not_configured(self):
        cfg = GarminConfig(token_file="/non/existent/tokens.json")
        uploader = GarminUploader(cfg)
        success, msg = uploader.test_connection()
        self.assertFalse(success)
        self.assertIn("not configured", msg)

    @patch("garminconnect.Garmin")
    def test_test_connection_success(self, mock_garmin_cls):
        mock_instance = MagicMock()
        mock_instance.get_full_name.return_value = "Mauro Druwel"
        mock_garmin_cls.return_value = mock_instance

        cfg = GarminConfig(email="user@example.com", password="pwd")
        uploader = GarminUploader(cfg)
        success, msg = uploader.test_connection()

        self.assertTrue(success)
        self.assertIn("Mauro Druwel", msg)
        mock_instance.login.assert_called_once()

    @patch("garminconnect.Garmin")
    def test_upload_tcx_success(self, mock_garmin_cls):
        mock_instance = MagicMock()
        mock_garmin_cls.return_value = mock_instance

        cfg = GarminConfig(email="user@example.com", password="pwd")
        uploader = GarminUploader(cfg)

        with tempfile.NamedTemporaryFile(suffix=".tcx") as tmp:
            tmp.write(b"<TCX>content</TCX>")
            tmp.flush()

            result = uploader.upload_tcx(Path(tmp.name))
            self.assertTrue(result)
            mock_instance.upload_activity.assert_called_once_with(tmp.name)

    @patch("garminconnect.Garmin")
    def test_upload_tcx_duplicate_handled_gracefully(self, mock_garmin_cls):
        mock_instance = MagicMock()
        mock_instance.upload_activity.side_effect = Exception("409 Conflict: Activity already exists")
        mock_garmin_cls.return_value = mock_instance

        cfg = GarminConfig(email="user@example.com", password="pwd")
        uploader = GarminUploader(cfg)

        with tempfile.NamedTemporaryFile(suffix=".tcx") as tmp:
            tmp.write(b"<TCX>content</TCX>")
            tmp.flush()

            result = uploader.upload_tcx(Path(tmp.name))
            # Duplicate conflict is treated as already uploaded / success
            self.assertTrue(result)

    @patch("garminconnect.Garmin")
    def test_upload_tcx_eu_consent_required(self, mock_garmin_cls):
        mock_instance = MagicMock()
        mock_instance.upload_activity.side_effect = Exception("412 - The user is from EU location, but upload consent is not yet granted")
        mock_garmin_cls.return_value = mock_instance

        cfg = GarminConfig(email="user@example.com", password="pwd")
        uploader = GarminUploader(cfg)

        with tempfile.NamedTemporaryFile(suffix=".tcx") as tmp:
            tmp.write(b"<TCX>content</TCX>")
            tmp.flush()

            result = uploader.upload_tcx(Path(tmp.name))
            self.assertFalse(result)

    @patch("time.sleep", return_value=None)
    @patch("garminconnect.Garmin")
    def test_upload_tcx_categorization_and_matching(self, mock_garmin_cls, mock_sleep):
        from datetime import datetime
        mock_instance = MagicMock()
        mock_instance.get_activities.return_value = [
            {"activityId": 99901, "startTimeLocal": "2026-09-20 10:00:00"},
            {"activityId": 99902, "startTimeLocal": "2026-09-21 15:00:00"},
        ]
        mock_garmin_cls.return_value = mock_instance

        cfg = GarminConfig(email="user@example.com", password="pwd")
        uploader = GarminUploader(cfg)

        with tempfile.NamedTemporaryFile(suffix=".tcx") as tmp:
            tmp.write(b"<TCX>content</TCX>")
            tmp.flush()

            result = uploader.upload_tcx(
                Path(tmp.name),
                title="🏊 Swim: LAGO Kortrijk Weide",
                sport="swim",
                start_time=datetime(2026, 9, 21, 15, 0, 0),
            )
            self.assertTrue(result)
            mock_instance.set_activity_type.assert_called_once_with(
                "99902", type_id=26, type_key="swimming", parent_type_id=17
            )
            mock_instance.set_activity_name.assert_called_once_with(
                "99902", "🏊 Swim: LAGO Kortrijk Weide"
            )

