"""
TrainingPeaks Multi-Source Sync Engine (Mauro Edition).
Orchestrates Strava telemetry, LAGO email bookings, and StudentApp pool reservations,
reconciling them into unified TrainingPeaks workouts with optional synthetic generation.
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
    SwimReservation,
    PdfTrainingSession,
    FusedWorkout,
    SyncResult,
    SyncBatchSummary,
)
from ..strava.oauth import StravaOAuthClient
from ..strava.api import StravaAPIClient
from ..sources.lago import LagoIMAPClient
from ..sources.studentapp import StudentAppClient
from ..sources.pdf import TrainingPdfClient
from ..fusion.reconciler import WorkoutReconciler
from ..fusion.synthetic_tcx import generate_synthetic_swim_tcx
from ..tcx.formatter import format_swim_tcx, format_xml_file, validate_tcx_file
from ..ai.analyzer import AIAnalyzer
from .state import SyncStateManager
from .email import TrainingPeaksEmailUploader
from ..garmin.client import GarminUploader


logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize activity title for filesystem use."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r'\s+', "_", clean.strip())
    return clean[:50] or "activity"


class SyncEngine:
    """Core pipeline engine for automated, multi-source workout synchronization."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        oauth_client: Optional[StravaOAuthClient] = None,
        api_client: Optional[StravaAPIClient] = None,
        lago_client: Optional[LagoIMAPClient] = None,
        studentapp_client: Optional[StudentAppClient] = None,
        state_manager: Optional[SyncStateManager] = None,
        ai_analyzer: Optional[AIAnalyzer] = None,
        reconciler: Optional[WorkoutReconciler] = None,
        garmin_uploader: Optional[GarminUploader] = None,
        pdf_client: Optional[TrainingPdfClient] = None,
    ):
        self.config = config or AppConfig.load()
        self.state_manager = state_manager or SyncStateManager(self.config.sync.state_file)

        # Optional PDF Training Plan client
        self.pdf_client = pdf_client or TrainingPdfClient(
            directory=self.config.training_pdf.directory,
            file_path=self.config.training_pdf.file_path,
        )

        # 1. Strava client initialization
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

        # 2. LAGO email reservation client
        self.lago_client = lago_client or LagoIMAPClient(self.config.lago)

        # 3. StudentApp booking client
        self.studentapp_client = studentapp_client or StudentAppClient(self.config.studentapp)

        # 4. Multi-source reconciler
        self.reconciler = reconciler or WorkoutReconciler(self.config.fusion)

        # 5. AI Analyzer
        self.ai_analyzer = ai_analyzer
        if not self.ai_analyzer and self.config.ai.enabled:
            self.ai_analyzer = AIAnalyzer(self.config.ai)

        # 6. Garmin Connect Bridge (auto-syncs into TrainingPeaks)
        self.garmin_uploader = garmin_uploader or GarminUploader(self.config.garmin)

        # 7. Optional email dispatcher
        self.email_uploader = TrainingPeaksEmailUploader(self.config.sync)

    def sync(
        self,
        athlete_id: Optional[int] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        force_ai: Optional[bool] = None,
        force: bool = False,
    ) -> SyncBatchSummary:
        """
        Execute automated multi-source synchronization.
        Gathers Strava telemetry, LAGO email bookings, and StudentApp reservations,
        fuses matching sessions, generates synthetic entries when watch is forgotten,
        and saves formatted TCX files for TrainingPeaks.
        """
        batch_summary = SyncBatchSummary()
        fetch_limit = limit or self.config.sync.limit

        strava_activities: List[ActivitySummary] = []
        actual_athlete_id: Optional[int] = athlete_id or self.config.strava.athlete_id

        # 1. Fetch Strava activities if configured
        if self.api_client and self.oauth_client:
            token = self.oauth_client.get_valid_token(actual_athlete_id)
            if token:
                actual_athlete_id = token.athlete_id
                logger.info("Fetching recent Strava activities for athlete %s...", token.athlete_name)
                raw_activities = self.api_client.list_activities(athlete_id=actual_athlete_id, per_page=fetch_limit)
                if raw_activities:
                    for act_dict in raw_activities:
                        if act_dict.get("id"):
                            strava_activities.append(ActivitySummary.from_strava_dict(act_dict))

        # 2. Fetch LAGO reservations if configured and enabled
        lago_reservations: List[SwimReservation] = []
        if self.config.lago.enabled and self.config.lago.is_configured:
            logger.info("Checking LAGO email reservations (IMAP / sample inbox)...")
            lago_reservations = self.lago_client.fetch_reservations()

        # 3. Fetch StudentApp bookings if configured and enabled
        studentapp_reservations: List[SwimReservation] = []
        if self.config.studentapp.enabled and self.config.studentapp.is_configured:
            logger.info("Checking StudentApp pool bookings (HAR file / sports API)...")
            studentapp_reservations = self.studentapp_client.fetch_reservations()

        # 4. Fetch PDF training plans if configured and enabled
        pdf_trainings: List[PdfTrainingSession] = []
        if self.config.training_pdf.enabled and self.config.training_pdf.is_configured:
            logger.info("Checking PDF training plans (%s)...", self.config.training_pdf.directory)
            pdf_trainings = self.pdf_client.fetch_trainings()

        # Guard: check if any data was found or any source configured & enabled
        total_sources_active = bool(
            self.api_client
            or (self.config.lago.enabled and self.config.lago.is_configured)
            or (self.config.studentapp.enabled and self.config.studentapp.is_configured)
            or (self.config.training_pdf.enabled and self.config.training_pdf.is_configured)
        )
        if not total_sources_active:
            logger.error("No active input sources enabled (Strava, LAGO, StudentApp, or PDF). Please check .env settings.")
            return batch_summary

        # 5. Multi-Source Reconciler / Fusion
        fused_workouts = self.reconciler.reconcile(
            strava_activities=strava_activities,
            lago_reservations=lago_reservations,
            studentapp_reservations=studentapp_reservations,
            pdf_trainings=pdf_trainings,
        )

        batch_summary.total_found = len(fused_workouts)
        output_dir = self.config.sync.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        should_analyze = (
            force_ai
            if force_ai is not None
            else (self.config.sync.auto_analyze and self.config.ai.enabled)
        )

        # 5. Process each fused workout
        for workout in fused_workouts:
            # Check sport filter
            if self.config.sync.sport_filter:
                filter_sport = self.config.sync.sport_filter.lower()
                if filter_sport not in workout.sport.value.lower():
                    continue

            # Idempotency check: check both session_id and strava id
            if not force:
                already_synced = self.state_manager.is_synced(workout.session_id)
                if not already_synced and workout.strava_activity:
                    already_synced = self.state_manager.is_synced(workout.strava_activity.id)

                if already_synced:
                    # If Garmin uploader is enabled, check if this activity still needs to be pushed to Garmin Connect
                    is_uploaded = self.state_manager.is_garmin_uploaded(workout.session_id)
                    if not is_uploaded and workout.strava_activity:
                        is_uploaded = self.state_manager.is_garmin_uploaded(workout.strava_activity.id)

                    if (
                        self.garmin_uploader
                        and self.config.garmin.enabled
                        and self.garmin_uploader.is_configured()
                        and not is_uploaded
                    ):
                        rec = self.state_manager.get_synced_activity(workout.session_id)
                        if not rec and workout.strava_activity:
                            rec = self.state_manager.get_synced_activity(workout.strava_activity.id)
                        tcx_path_str = rec.get("tcx_path", "") if rec else None
                        if tcx_path_str:
                            tcx_p = Path(tcx_path_str)
                            if not tcx_p.is_absolute():
                                tcx_p = self.config.sync.output_dir.parent / tcx_p
                            if not tcx_p.is_file():
                                tcx_p = self.config.sync.output_dir / Path(tcx_path_str).name
                            if tcx_p.is_file():
                                if dry_run:
                                    logger.info("[Dry Run] Would upload previously synced workout to Garmin Connect: %s", tcx_p.name)
                                else:
                                    logger.info("Uploading previously synced workout to Garmin Connect: %s", tcx_p.name)
                                    if workout.sport.value.lower() == "swim":
                                        garmin_ok = bool(self.garmin_uploader.create_manual_swim_activity(
                                            start_time=workout.start_time,
                                            distance_meters=workout.distance_meters,
                                            duration_seconds=workout.duration_seconds,
                                            title=workout.title,
                                            description=workout.description or f"🏊 Verified Swim Session ({'+'.join(workout.sources).upper()})",
                                        ))
                                    else:
                                        garmin_ok = bool(self.garmin_uploader.upload_tcx(
                                            tcx_p,
                                            title=workout.title,
                                            sport=workout.sport.value,
                                            start_time=workout.start_time,
                                        ))
                                    if garmin_ok:
                                        self.state_manager.mark_garmin_uploaded(workout.session_id, True)
                                        if workout.strava_activity:
                                            self.state_manager.mark_garmin_uploaded(workout.strava_activity.id, True)

                    logger.debug("Workout %s already synced, skipping.", workout.session_id)
                    batch_summary.already_synced += 1
                    continue

            sources_label = "+".join(workout.sources).upper()
            logger.info("Processing workout: [%s] %s (Sources: %s)", workout.session_id, workout.title, sources_label)

            if dry_run:
                logger.info("[Dry Run] Would sync: %s (%s)", workout.title, sources_label)
                batch_summary.newly_synced += 1
                batch_summary.results.append(
                    SyncResult(
                        activity_id=workout.session_id,
                        athlete_id=actual_athlete_id,
                        success=True,
                        sources=workout.sources,
                        has_watch_data=workout.has_watch_data,
                    )
                )
                continue

            # Real execution
            result = self._process_fused_workout(
                workout=workout,
                athlete_id=actual_athlete_id,
                output_dir=output_dir,
                should_analyze=should_analyze,
            )

            batch_summary.results.append(result)
            if result.success:
                batch_summary.newly_synced += 1
            else:
                batch_summary.failed += 1

        return batch_summary

    def _process_fused_workout(
        self,
        workout: FusedWorkout,
        athlete_id: Optional[int],
        output_dir: Path,
        should_analyze: bool,
    ) -> SyncResult:
        """Download or generate TCX, apply TrainingPeaks formatting, analyze, and dispatch."""
        date_str = workout.start_time.strftime("%Y-%m-%d")
        safe_name = sanitize_filename(workout.title)
        tcx_filename = f"{date_str}_{workout.sport.value}_{safe_name}_{workout.session_id}.tcx"
        tcx_path = output_dir / tcx_filename

        try:
            if workout.has_watch_data and workout.strava_activity and self.api_client:
                # Real watch telemetry from Strava
                downloaded = self.api_client.download_tcx(athlete_id, workout.strava_activity.id, str(tcx_path))
                if not downloaded or not tcx_path.exists():
                    return SyncResult(
                        activity_id=workout.session_id,
                        athlete_id=athlete_id,
                        success=False,
                        error_message="TCX download returned empty or file not written",
                        sources=workout.sources,
                        has_watch_data=True,
                    )
            else:
                # Synthetic workout generation (e.g. watch forgotten!)
                tcx_content = generate_synthetic_swim_tcx(workout=workout)
                with open(tcx_path, "w", encoding="utf-8") as f:
                    f.write(tcx_content)
                logger.info("Generated synthetic swim TCX file: %s", tcx_path.name)

            # TCX post-processing
            if workout.sport in (Sport.SWIM, Sport.OTHER):
                format_swim_tcx(str(tcx_path), target_duration_seconds=workout.duration_seconds)
            format_xml_file(str(tcx_path))

            # Validation
            valid, tcx_data = validate_tcx_file(str(tcx_path))
            if not valid:
                logger.warning("Generated TCX file failed validation: %s", tcx_path)

            # Optional AI Analysis
            analysis_text: Optional[str] = None
            analysis_path: Optional[str] = None

            if should_analyze and self.ai_analyzer:
                try:
                    logger.info("Generating AI coaching analysis for %s...", workout.title)
                    if tcx_data:
                        analysis_text = self.ai_analyzer.analyze(tcx_data, workout.sport)
                    if analysis_text and self.config.sync.save_analysis_file:
                        analysis_filename = f"{date_str}_{workout.sport.value}_{safe_name}_{workout.session_id}_analysis.md"
                        analysis_file_path = output_dir / analysis_filename
                        with open(analysis_file_path, "w", encoding="utf-8") as f:
                            f.write(f"# TrainingPeaks Analysis: {workout.title}\n\n")
                            f.write(f"- **Date**: {workout.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                            f.write(f"- **Sport**: {workout.sport.value}\n")
                            f.write(f"- **Sources**: {', '.join(s.upper() for s in workout.sources)}\n")
                            f.write(f"- **Watch Data**: {'Recorded on watch' if workout.has_watch_data else 'Synthetic (Watch forgotten)'}\n")
                            f.write(f"- **Distance**: {workout.distance_meters / 1000:.2f} km\n\n")
                            f.write(f"### Description\n{workout.description}\n\n")
                            f.write("### AI Coaching Report\n")
                            f.write(analysis_text)
                        analysis_path = str(analysis_file_path)
                except Exception as ai_err:
                    logger.warning("AI analysis failed for %s: %s", workout.session_id, ai_err)

            # Garmin Connect Bridge (automatically syncs to TrainingPeaks)
            garmin_uploaded = False
            if self.garmin_uploader and self.config.garmin.enabled and self.garmin_uploader.is_configured():
                if workout.sport.value.lower() == "swim":
                    aid = self.garmin_uploader.create_manual_swim_activity(
                        start_time=workout.start_time,
                        distance_meters=workout.distance_meters,
                        duration_seconds=workout.duration_seconds,
                        title=workout.title,
                        description=workout.description or f"🏊 Verified Swim Session ({'+'.join(workout.sources).upper()})",
                    )
                    garmin_uploaded = bool(aid)
                else:
                    garmin_uploaded = bool(
                        self.garmin_uploader.upload_tcx(
                            tcx_path,
                            title=workout.title,
                            sport=workout.sport.value,
                            start_time=workout.start_time,
                        )
                    )

            # Optional email dispatch
            if self.email_uploader.can_send():
                self.email_uploader.send_tcx(tcx_path, subject=f"TrainingPeaks Activity: {workout.title}")

            # Persist state
            self.state_manager.record_synced(
                activity_id=workout.session_id,
                athlete_id=athlete_id,
                name=workout.title,
                sport=workout.sport.value,
                start_date=workout.start_time.isoformat(),
                tcx_path=str(tcx_path),
                analyzed=bool(analysis_text),
                analysis_path=analysis_path,
                sources=workout.sources,
                has_watch_data=workout.has_watch_data,
                garmin_uploaded=garmin_uploaded,
            )

            # Also record underlying Strava ID if present to maintain backward compatibility
            if workout.strava_activity:
                self.state_manager.record_synced(
                    activity_id=workout.strava_activity.id,
                    athlete_id=athlete_id,
                    name=workout.title,
                    sport=workout.sport.value,
                    start_date=workout.start_time.isoformat(),
                    tcx_path=str(tcx_path),
                    analyzed=bool(analysis_text),
                    analysis_path=analysis_path,
                    sources=workout.sources,
                    has_watch_data=workout.has_watch_data,
                    garmin_uploaded=garmin_uploaded,
                )

            logger.info("Successfully synced %s to %s", workout.title, tcx_path.name)
            return SyncResult(
                activity_id=workout.session_id,
                athlete_id=athlete_id,
                success=True,
                tcx_path=str(tcx_path),
                analysis_path=analysis_path,
                analysis_text=analysis_text,
                sources=workout.sources,
                has_watch_data=workout.has_watch_data,
            )

        except Exception as err:
            logger.error("Error processing workout %s: %s", workout.session_id, err)
            return SyncResult(
                activity_id=workout.session_id,
                athlete_id=athlete_id,
                success=False,
                error_message=str(err),
                sources=workout.sources,
                has_watch_data=workout.has_watch_data,
            )

    def _process_single_activity(
        self,
        athlete_id: int,
        summary: ActivitySummary,
        output_dir: Path,
        should_analyze: bool,
    ) -> SyncResult:
        """Backward compatibility wrapper for single Strava activity sync."""
        workout = FusedWorkout(
            session_id=f"fused_strava_{summary.id}",
            sport=summary.sport,
            start_time=summary.start_datetime,
            duration_seconds=summary.elapsed_time_seconds,
            distance_meters=summary.distance_meters,
            sources=["strava"],
            has_watch_data=True,
            title=summary.name,
            description=f"Strava activity {summary.id}",
            strava_activity=summary,
        )
        return self._process_fused_workout(
            workout=workout,
            athlete_id=athlete_id,
            output_dir=output_dir,
            should_analyze=should_analyze,
        )
