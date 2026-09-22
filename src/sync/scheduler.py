"""
Scheduler for automated periodic sync and daemon execution.
"""
import logging
import signal
import sys
import time
from typing import Optional

from ..config import AppConfig
from .engine import SyncEngine
from ..models import SyncBatchSummary


logger = logging.getLogger(__name__)


class SyncScheduler:
    """Manages continuous daemon execution or one-shot cron jobs."""

    def __init__(self, engine: Optional[SyncEngine] = None, config: Optional[AppConfig] = None):
        self.config = config or AppConfig.load()
        self.engine = engine or SyncEngine(self.config)
        self._stop_requested = False

        # Register termination signal handlers
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        """Handle interrupt signals gracefully."""
        logger.info("Shutdown requested (signal %d), finishing current run...", signum)
        self._stop_requested = True

    def run_once(
        self,
        athlete_id: Optional[int] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        force_ai: Optional[bool] = None,
    ) -> SyncBatchSummary:
        """Execute a single sync run (ideal for crontab)."""
        logger.info("Running single sync job...")
        summary = self.engine.sync(
            athlete_id=athlete_id,
            limit=limit,
            dry_run=dry_run,
            force_ai=force_ai,
        )
        logger.info(
            "Sync run completed. %d newly synced, %d already synced, %d failed.",
            summary.newly_synced,
            summary.already_synced,
            summary.failed,
        )
        return summary

    def run_daemon(
        self,
        interval_seconds: Optional[int] = None,
        athlete_id: Optional[int] = None,
        limit: Optional[int] = None,
        force_ai: Optional[bool] = None,
    ) -> None:
        """Run continuous loop sleeping for interval_seconds between sync runs."""
        interval = interval_seconds or self.config.sync.interval_seconds
        logger.info("Starting Sync Daemon (checking every %d seconds)...", interval)
        print(f"🔄 Strava to TrainingPeaks Sync Daemon started (interval: {interval}s). Press Ctrl+C to stop.")

        iteration = 0
        while not self._stop_requested:
            iteration += 1
            logger.info("Starting sync cycle #%d", iteration)

            try:
                summary = self.engine.sync(
                    athlete_id=athlete_id,
                    limit=limit,
                    force_ai=force_ai,
                )
                print(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Cycle #{iteration} completed: "
                    f"{summary.newly_synced} synced, {summary.already_synced} skipped, {summary.failed} failed."
                )
            except Exception as err:
                logger.error("Error during sync cycle #%d: %s", iteration, err)

            # Sleep in 1-second chunks so we can stop immediately on SIGINT/SIGTERM
            for _ in range(interval):
                if self._stop_requested:
                    break
                time.sleep(1)

        logger.info("Sync daemon stopped gracefully.")
        print("👋 Sync daemon stopped.")
