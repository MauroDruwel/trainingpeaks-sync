"""
Unit tests for SyncEngine synchronization pipeline.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.config import AppConfig, StravaConfig, AIConfig, SyncConfig
from src.models import AthleteToken, Sport, ActivitySummary
from src.sync.engine import SyncEngine, sanitize_filename
from src.sync.state import SyncStateManager


class TestSyncEngine(unittest.TestCase):
    """Test automated synchronization engine."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name) / "synced"
        self.state_file = Path(self.temp_dir.name) / "state.json"

        self.config = AppConfig(
            strava=StravaConfig(client_id="id", client_secret="sec"),
            ai=AIConfig(enabled=False),
            sync=SyncConfig(output_dir=self.output_dir, state_file=self.state_file, limit=5)
        )
        self.state_mgr = SyncStateManager(self.state_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("Simple Name"), "Simple_Name")
        self.assertEqual(sanitize_filename("Run / 10k: fast?"), "Run_10k_fast")
        self.assertEqual(sanitize_filename("   "), "activity")

    def test_sync_no_client(self):
        engine = SyncEngine(config=self.config, oauth_client=None, api_client=None)
        summary = engine.sync()
        self.assertEqual(summary.total_found, 0)
        self.assertEqual(summary.newly_synced, 0)

    def test_sync_no_valid_token(self):
        mock_oauth = MagicMock()
        mock_oauth.get_valid_token.return_value = None
        mock_api = MagicMock()

        engine = SyncEngine(
            config=self.config,
            oauth_client=mock_oauth,
            api_client=mock_api,
            state_manager=self.state_mgr
        )
        summary = engine.sync()
        self.assertEqual(summary.total_found, 0)

    def test_sync_pipeline_success(self):
        mock_oauth = MagicMock()
        mock_token = AthleteToken(
            athlete_id=777,
            athlete_name="Mauro",
            access_token="tok",
            refresh_token="ref",
            expires_at=9999999999
        )
        mock_oauth.get_valid_token.return_value = mock_token

        mock_api = MagicMock()
        mock_api.list_activities.return_value = [
            {
                "id": 1001,
                "name": "Tempo Ride",
                "type": "Ride",
                "start_date": "2026-09-22T08:00:00Z",
                "distance": 35000,
                "elapsed_time": 3600
            },
            {
                "id": 1002,
                "name": "Recovery Run",
                "type": "Run",
                "start_date": "2026-09-21T08:00:00Z",
                "distance": 5000,
                "elapsed_time": 1800
            }
        ]

        # Mock download_tcx to create a dummy valid file
        def fake_download_tcx(athlete_id, activity_id, output_path):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write("<TrainingCenterDatabase></TrainingCenterDatabase>")
            return output_path

        mock_api.download_tcx.side_effect = fake_download_tcx

        engine = SyncEngine(
            config=self.config,
            oauth_client=mock_oauth,
            api_client=mock_api,
            state_manager=self.state_mgr
        )

        with patch("src.sync.engine.validate_tcx_file", return_value=(True, MagicMock())), \
             patch("src.sync.engine.format_xml_file"):

            # First run: should sync 2 activities
            summary = engine.sync()
            self.assertEqual(summary.total_found, 2)
            self.assertEqual(summary.newly_synced, 2)
            self.assertEqual(summary.already_synced, 0)
            self.assertEqual(summary.failed, 0)
            self.assertTrue(self.state_mgr.is_synced(1001))
            self.assertTrue(self.state_mgr.is_synced(1002))

            # Second run: activities are already synced, should skip!
            summary2 = engine.sync()
            self.assertEqual(summary2.total_found, 2)
            self.assertEqual(summary2.newly_synced, 0)
            self.assertEqual(summary2.already_synced, 2)

            # Third run with force=True: should re-sync despite existing state!
            summary3 = engine.sync(force=True)
            self.assertEqual(summary3.total_found, 2)
            self.assertEqual(summary3.newly_synced, 2)
            self.assertEqual(summary3.already_synced, 0)

    def test_sync_dry_run(self):
        mock_oauth = MagicMock()
        mock_token = AthleteToken(777, "Mauro", "tok", "ref", 9999999999)
        mock_oauth.get_valid_token.return_value = mock_token

        mock_api = MagicMock()
        mock_api.list_activities.return_value = [
            {"id": 2001, "name": "Morning Swim", "type": "Swim", "start_date": "2026-09-22T08:00:00Z"}
        ]

        engine = SyncEngine(
            config=self.config,
            oauth_client=mock_oauth,
            api_client=mock_api,
            state_manager=self.state_mgr
        )

        summary = engine.sync(dry_run=True)
        self.assertEqual(summary.total_found, 1)
        self.assertEqual(summary.newly_synced, 1)
        # In dry run, file should not be created and state not persisted
        self.assertFalse(self.state_mgr.is_synced(2001))
        mock_api.download_tcx.assert_not_called()
