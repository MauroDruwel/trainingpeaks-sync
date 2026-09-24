"""
Unit tests for SyncStateManager persistence and tracking.
"""
import tempfile
import unittest
from pathlib import Path

from src.sync.state import SyncStateManager


class TestSyncStateManager(unittest.TestCase):
    """Test state manager file operations and history recording."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / ".sync_state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_state_empty(self):
        manager = SyncStateManager(self.state_file)
        self.assertEqual(manager.get_total_synced_count(), 0)
        self.assertIsNone(manager.get_last_sync())
        self.assertFalse(manager.is_synced(12345))

    def test_record_and_query_activity(self):
        manager = SyncStateManager(self.state_file)
        manager.record_synced(
            activity_id=101,
            athlete_id=123,
            name="Morning Interval Run",
            sport="Run",
            start_date="2026-09-22T07:00:00Z",
            tcx_path="/path/to/101.tcx",
            analyzed=True,
            analysis_path="/path/to/101_analysis.md"
        )

        self.assertTrue(manager.is_synced(101))
        self.assertEqual(manager.get_total_synced_count(), 1)
        self.assertIsNotNone(manager.get_last_sync())

        record = manager.get_synced_activity(101)
        self.assertIsNotNone(record)
        self.assertEqual(record["name"], "Morning Interval Run")
        self.assertEqual(record["sport"], "Run")
        self.assertTrue(record["analyzed"])

        # Reload from disk into a fresh manager instance to verify persistence
        new_manager = SyncStateManager(self.state_file)
        self.assertTrue(new_manager.is_synced(101))
        self.assertEqual(new_manager.get_total_synced_count(), 1)

    def test_corrupted_file_recovery(self):
        # Write invalid JSON to state file
        with open(self.state_file, "w") as f:
            f.write("{invalid json content!!!")

        manager = SyncStateManager(self.state_file)
        self.assertEqual(manager.get_total_synced_count(), 0)

    def test_garmin_uploaded_tracking(self):
        manager = SyncStateManager(self.state_file)
        manager.record_synced(
            activity_id="act_1",
            athlete_id=None,
            name="Swim",
            sport="Swim",
            start_date="2026-09-24T08:00:00Z",
            tcx_path="/tmp/act_1.tcx",
            garmin_uploaded=False,
        )
        self.assertFalse(manager.is_garmin_uploaded("act_1"))
        manager.mark_garmin_uploaded("act_1", True)
        self.assertTrue(manager.is_garmin_uploaded("act_1"))

        # Reload
        new_mgr = SyncStateManager(self.state_file)
        self.assertTrue(new_mgr.is_garmin_uploaded("act_1"))
        self.assertFalse(manager.is_synced(999))
