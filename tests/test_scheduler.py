"""
Unit tests for SyncScheduler cron and daemon runner.
"""
import unittest
from unittest.mock import MagicMock, patch
import signal

from src.sync.scheduler import SyncScheduler
from src.models import SyncBatchSummary


class TestSyncScheduler(unittest.TestCase):
    """Test scheduler for cron jobs and daemon mode."""

    def test_run_once(self):
        mock_engine = MagicMock()
        mock_summary = SyncBatchSummary(total_found=5, newly_synced=3, already_synced=2)
        mock_engine.sync.return_value = mock_summary

        scheduler = SyncScheduler(engine=mock_engine)
        result = scheduler.run_once(athlete_id=123, limit=10, dry_run=False, force_ai=True)

        self.assertEqual(result, mock_summary)
        mock_engine.sync.assert_called_once_with(
            athlete_id=123,
            limit=10,
            dry_run=False,
            force_ai=True,
            force=False,
        )

    def test_run_once_force(self):
        mock_engine = MagicMock()
        mock_summary = SyncBatchSummary(total_found=5, newly_synced=5, already_synced=0)
        mock_engine.sync.return_value = mock_summary

        scheduler = SyncScheduler(engine=mock_engine)
        result = scheduler.run_once(athlete_id=123, limit=10, dry_run=False, force_ai=True, force=True)

        self.assertEqual(result, mock_summary)
        mock_engine.sync.assert_called_once_with(
            athlete_id=123,
            limit=10,
            dry_run=False,
            force_ai=True,
            force=True,
        )

    def test_run_daemon_stops_on_signal(self):
        mock_engine = MagicMock()
        mock_engine.sync.return_value = SyncBatchSummary()

        scheduler = SyncScheduler(engine=mock_engine)

        def stop_after_one_iteration(*args, **kwargs):
            scheduler._stop_requested = True
            return SyncBatchSummary()

        mock_engine.sync.side_effect = stop_after_one_iteration

        with patch("time.sleep"):
            scheduler.run_daemon(interval_seconds=10)

        mock_engine.sync.assert_called_once()
        self.assertTrue(scheduler._stop_requested)
