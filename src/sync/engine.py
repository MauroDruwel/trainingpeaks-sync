"""
Automated Strava to TrainingPeaks sync engine.
Coordinates fetching from Strava, formatting TCX, running AI analysis, and dispatching.
"""
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..config import AppConfig
from ..models import (
    Sport,
    ActivitySummary,
    SyncResult,
    SyncBatchSummary,
)
from ..strava.oauth import StravaOAuthClient
from ..strava.api import StravaAPIClient
from ..tcx.formatter import format_swim_tcx, format_xml_file, validate_tcx_file
from ..ai.analyzer import AIAnalyzer
from .state import SyncStateManager
from .email import TrainingPeaksEmailUploader


logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize activity title for filesystem use."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r'\s+', "_", clean.strip())
    return clean[:50] or "activity"


class SyncEngine:
    """Core pipeline engine for automated, unattended syncing."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        oauth_client: Optional[StravaOAuthClient] = None,
        api_client: Optional[StravaAPIClient] = None,
        state_manager: Optional[SyncStateManager] = None,
        ai_analyzer: Optional[AIAnalyzer] = None,
    ):
        self.config = config or AppConfig.load()
        self.state_manager = state_manager or SyncStateManager(self.config.sync.state_file)

        self.oauth_client = oauth_client
        self.api_client = api_client
        if not self.oauth_client and self.config.strava.is_oauth_configured:
            try:
                self.oauth_client = StravaOAuthClient(self.config.strava.token_file)
                self.api_client = StravaAPIClient(self.oauth_client)
            except Exception as err:
                logger.warning("Could not initialize Strava OAuth client: %s", err)

        if not self.api_client and self.oauth_client:
            self.api_client = StravaAPIClient(self.oauth_client)

        self.ai_analyzer = ai_analyzer
        if not self.ai_analyzer and self.config.ai.enabled:
            self.ai_analyzer = AIAnalyzer(self.config.ai)

        self.email_uploader = TrainingPeaksEmailUploader(self.config.sync)

    def sync(
        self,
        athlete_id: Optional[int] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        force_ai: Optional[bool] = None,
    ) -> SyncBatchSummary:
        """
        Execute automated sync check for new activities.
        """
        batch_summary = SyncBatchSummary()

        if not self.api_client or not self.oauth_client:
            logger.error(
                "Strava API client is not configured. Please set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET."
            )
            return batch_summary

        target_athlete_id = athlete_id or self.config.strava.athlete_id
        valid_token = self.oauth_client.get_valid_token(target_athlete_id)
        if not valid_token:
            logger.error("No valid authorization token found. Please run authentication first.")
            return batch_summary

        actual_athlete_id = valid_token.athlete_id
        fetch_limit = limit or self.config.sync.limit

        logger.info(
            "Checking Strava activities for athlete %s (ID: %s, limit: %d)...",
            valid_token.athlete_name,
            actual_athlete_id,
            fetch_limit
        )

        activities_raw = self.api_client.list_activities(
            athlete_id=actual_athlete_id,
            per_page=fetch_limit
        )

        if activities_raw is None:
            logger.error("Failed to retrieve activities from Strava API.")
            return batch_summary

        batch_summary.total_found = len(activities_raw)
        output_dir = self.config.sync.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        should_analyze = (
            force_ai
            if force_ai is not None
            else (self.config.sync.auto_analyze and self.config.ai.enabled)
        )

        for act_data in activities_raw:
            activity_id = act_data.get("id")
            if not activity_id:
                continue

            summary = ActivitySummary.from_strava_dict(act_data)

            # Sport filter check
            if self.config.sync.sport_filter:
                filter_sport = self.config.sync.sport_filter.lower()
                if filter_sport not in summary.sport.value.lower() and filter_sport not in summary.strava_type.lower():
                    logger.debug("Skipping activity %s (sport %s != filter)", activity_id, summary.sport.value)
                    continue

            # Idempotency check: skip already synced
            if self.state_manager.is_synced(activity_id):
                logger.debug("Activity %s already synced, skipping.", activity_id)
                batch_summary.already_synced += 1
                continue

            logger.info("New activity found: [%s] %s (%s)", activity_id, summary.name, summary.sport.value)

            if dry_run:
                logger.info("[Dry Run] Would sync activity %s: %s", activity_id, summary.name)
                batch_summary.newly_synced += 1
                batch_summary.results.append(
                    SyncResult(
                        activity_id=activity_id,
                        athlete_id=actual_athlete_id,
                        success=True,
                        tcx_path=None
                    )
                )
                continue

            # Real sync execution
            result = self._process_single_activity(
                athlete_id=actual_athlete_id,
                summary=summary,
                output_dir=output_dir,
                should_analyze=should_analyze
            )

            batch_summary.results.append(result)
            if result.success:
                batch_summary.newly_synced += 1
            else:
                batch_summary.failed += 1

        return batch_summary

    def _process_single_activity(
        self,
        athlete_id: int,
        summary: ActivitySummary,
        output_dir: Path,
        should_analyze: bool,
    ) -> SyncResult:
        """Download, format, optionally analyze, and store a single activity."""
        date_str = summary.start_date[:10]
        safe_name = sanitize_filename(summary.name)
        tcx_filename = f"{date_str}_{summary.sport.value}_{safe_name}_{summary.id}.tcx"
        tcx_path = output_dir / tcx_filename

        try:
            downloaded = self.api_client.download_tcx(athlete_id, summary.id, str(tcx_path))
            if not downloaded or not tcx_path.exists():
                logger.error("Failed to download TCX for activity %s", summary.id)
                return SyncResult(
                    activity_id=summary.id,
                    athlete_id=athlete_id,
                    success=False,
                    error_message="TCX download returned empty or file not written"
                )

            # Post-process TCX according to sport
            if summary.sport in (Sport.SWIM, Sport.OTHER):
                format_swim_tcx(str(tcx_path))
            format_xml_file(str(tcx_path))

            # Run validation
            valid, tcx_data = validate_tcx_file(str(tcx_path))
            if not valid:
                logger.warning("Generated TCX file failed validation: %s", tcx_path)

            # Optional AI Analysis
            analysis_text: Optional[str] = None
            analysis_path: Optional[str] = None

            if should_analyze and self.ai_analyzer:
                try:
                    logger.info("Generating AI analysis for %s...", summary.name)
                    if tcx_data:
                        analysis_text = self.ai_analyzer.analyze(tcx_data, summary.sport)
                    if analysis_text and self.config.sync.save_analysis_file:
                        analysis_filename = f"{date_str}_{summary.sport.value}_{safe_name}_{summary.id}_analysis.md"
                        analysis_file_path = output_dir / analysis_filename
                        with open(analysis_file_path, "w", encoding="utf-8") as f:
                            f.write(f"# Training Analysis: {summary.name}\n\n")
                            f.write(f"- **Date**: {summary.start_date}\n")
                            f.write(f"- **Sport**: {summary.sport.value}\n")
                            f.write(f"- **Distance**: {summary.distance_meters / 1000:.2f} km\n\n")
                            f.write(analysis_text)
                        analysis_path = str(analysis_file_path)
                        logger.info("Saved AI analysis report to: %s", analysis_path)
                except Exception as ai_err:
                    logger.warning("AI analysis failed for activity %s: %s", summary.id, ai_err)

            # Optional TrainingPeaks email upload
            if self.email_uploader.can_send():
                self.email_uploader.send_tcx(tcx_path, subject=f"TrainingPeaks Activity: {summary.name}")

            # Record in sync state
            self.state_manager.record_synced(
                activity_id=summary.id,
                athlete_id=athlete_id,
                name=summary.name,
                sport=summary.sport.value,
                start_date=summary.start_date,
                tcx_path=str(tcx_path),
                analyzed=bool(analysis_text),
                analysis_path=analysis_path,
            )

            logger.info("Successfully synced activity %s to %s", summary.id, tcx_path.name)
            return SyncResult(
                activity_id=summary.id,
                athlete_id=athlete_id,
                success=True,
                tcx_path=str(tcx_path),
                analysis_path=analysis_path,
                analysis_text=analysis_text,
            )

        except Exception as err:
            logger.error("Error processing activity %s: %s", summary.id, str(err))
            return SyncResult(
                activity_id=summary.id,
                athlete_id=athlete_id,
                success=False,
                error_message=str(err)
            )
