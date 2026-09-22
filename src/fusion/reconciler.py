"""
Multi-Source Workout Reconciler & Fusion Engine.
Correlates Strava watch telemetry, LAGO email bookings, and StudentApp reservations.
Generates synthetic activities when the watch was forgotten.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Set

from ..config import FusionConfig
from ..models import (
    Sport,
    ActivitySummary,
    SwimReservation,
    FusedWorkout,
)


logger = logging.getLogger(__name__)


class WorkoutReconciler:
    """Correlates multiple data sources into unified, reconciled workouts."""

    def __init__(self, config: Optional[FusionConfig] = None):
        self.config = config or FusionConfig()

    def reconcile(
        self,
        strava_activities: List[ActivitySummary],
        lago_reservations: List[SwimReservation],
        studentapp_reservations: List[SwimReservation],
    ) -> List[FusedWorkout]:
        """
        Reconcile Strava activities, LAGO reservations, and StudentApp bookings
        into unified FusedWorkout instances.
        """
        fused_workouts: List[FusedWorkout] = []
        matched_lago: Set[str] = set()
        matched_student: Set[str] = set()
        matched_strava: Set[int] = set()

        window = timedelta(minutes=self.config.time_window_minutes)

        # 1. First, pair Strava activities with matching reservations
        for strava_act in strava_activities:
            act_time = strava_act.start_datetime

            # Find matching LAGO reservation
            matching_lago = None
            for lago in lago_reservations:
                if abs((lago.start_time - act_time).total_seconds()) <= window.total_seconds():
                    matching_lago = lago
                    matched_lago.add(lago.reservation_id)
                    break

            # Find matching StudentApp reservation
            matching_student = None
            for stud in studentapp_reservations:
                if abs((stud.start_time - act_time).total_seconds()) <= window.total_seconds():
                    matching_student = stud
                    matched_student.add(stud.reservation_id)
                    break

            sources = ["strava"]
            if matching_lago:
                sources.append("lago")
            if matching_student:
                sources.append("studentapp")

            facility_name = ""
            if matching_lago:
                facility_name = matching_lago.facility
            elif matching_student:
                facility_name = matching_student.facility

            # Calculate duration:
            # When resting in the pool, Strava often cuts off time or auto-pauses.
            # We preserve the full session slot (from matched LAGO/StudentApp booking
            # or default 1h45m / 6300s), ensuring the athlete gets credited for the full slot.
            if strava_act.sport == Sport.SWIM:
                slot_duration = (
                    matching_lago.duration_seconds
                    if matching_lago and matching_lago.duration_seconds
                    else (
                        matching_student.duration_seconds
                        if matching_student and matching_student.duration_seconds
                        else self.config.synthetic_swim_duration_seconds
                    )
                )
                duration_sec = max(strava_act.elapsed_time_seconds, slot_duration)
            else:
                duration_sec = strava_act.elapsed_time_seconds

            title = strava_act.name
            if strava_act.sport == Sport.SWIM and facility_name:
                title = f"🏊 Swim: {facility_name}"

            # Build rich description showing matched sources
            desc_lines = [
                f"🏊 TrainingPeaks Fused Workout ({strava_act.sport.value})",
                f"• Verified Sources: {', '.join(s.upper() for s in sources)}",
                f"• Watch Telemetry: Recorded (Distance: {strava_act.distance_meters/1000:.2f} km)",
            ]
            if strava_act.sport == Sport.SWIM and duration_sec > strava_act.elapsed_time_seconds:
                desc_lines.append(
                    f"• Duration: {duration_sec // 60} mins (Full slot preserved; watch recorded: {strava_act.elapsed_time_seconds // 60} mins)"
                )
            elif strava_act.sport == Sport.SWIM:
                desc_lines.append(f"• Duration: {duration_sec // 60} mins")

            if matching_lago:
                desc_lines.append(f"• LAGO Reservation: #{matching_lago.reservation_id} ({matching_lago.facility})")
            if matching_student:
                desc_lines.append(f"• StudentApp Booking: #{matching_student.reservation_id} ({matching_student.facility})")

            workout = FusedWorkout(
                session_id=f"fused_strava_{strava_act.id}",
                sport=strava_act.sport,
                start_time=act_time,
                duration_seconds=duration_sec,
                distance_meters=strava_act.distance_meters,
                sources=sources,
                has_watch_data=True,
                title=title,
                description="\n".join(desc_lines),
                strava_activity=strava_act,
                lago_reservation=matching_lago,
                studentapp_reservation=matching_student,
            )

            fused_workouts.append(workout)
            matched_strava.add(strava_act.id)

        # 2. Reconcile remaining unmatched reservations (LAGO and StudentApp)
        # Check if any unmatched LAGO and StudentApp match each other
        unmatched_lago_list = [r for r in lago_reservations if r.reservation_id not in matched_lago]
        unmatched_student_list = [r for r in studentapp_reservations if r.reservation_id not in matched_student]

        paired_reservations: List[Tuple[Optional[SwimReservation], Optional[SwimReservation]]] = []

        for lago in unmatched_lago_list:
            matched_stud = None
            for stud in unmatched_student_list:
                if stud.reservation_id not in matched_student:
                    if abs((stud.start_time - lago.start_time).total_seconds()) <= window.total_seconds():
                        matched_stud = stud
                        matched_student.add(stud.reservation_id)
                        break
            paired_reservations.append((lago, matched_stud))
            matched_lago.add(lago.reservation_id)

        # Add remaining unmatched studentapp reservations
        for stud in unmatched_student_list:
            if stud.reservation_id not in matched_student:
                paired_reservations.append((None, stud))
                matched_student.add(stud.reservation_id)

        # 3. Create Synthetic Workouts for reservations where watch was forgotten!
        if self.config.auto_generate_synthetic_if_watch_forgotten:
            for lago_res, stud_res in paired_reservations:
                primary_res = lago_res or stud_res
                if not primary_res:
                    continue

                sources = []
                if lago_res:
                    sources.append("lago")
                if stud_res:
                    sources.append("studentapp")

                facility = primary_res.facility
                start_dt = primary_res.start_time
                duration = primary_res.duration_seconds or self.config.synthetic_swim_duration_seconds
                distance = self.config.synthetic_swim_distance_meters

                title = f"🏊 Swim: {facility} (Reservation Verified)"
                desc_lines = [
                    f"🏊 TrainingPeaks Verified Swim (Watch Forgotten)",
                    f"• Verified Sources: {', '.join(s.upper() for s in sources)}",
                    f"• Facility: {facility}",
                    f"• Duration: {duration // 60} minutes",
                    f"• Estimated Distance: {distance / 1000:.2f} km",
                    "• Note: Recorded from verified pool booking. Telemetry was not captured by watch.",
                ]
                if lago_res:
                    desc_lines.append(f"• LAGO Ref: #{lago_res.reservation_id}")
                if stud_res:
                    desc_lines.append(f"• StudentApp Ref: #{stud_res.reservation_id}")

                res_id_tag = (lago_res.reservation_id if lago_res else stud_res.reservation_id) if stud_res else "res"
                synthetic_workout = FusedWorkout(
                    session_id=f"synthetic_{start_dt.strftime('%Y%m%d_%H%M')}_{res_id_tag}",
                    sport=Sport.SWIM,
                    start_time=start_dt,
                    duration_seconds=duration,
                    distance_meters=distance,
                    sources=sources,
                    has_watch_data=False,
                    title=title,
                    description="\n".join(desc_lines),
                    lago_reservation=lago_res,
                    studentapp_reservation=stud_res,
                )

                fused_workouts.append(synthetic_workout)
                logger.info(
                    "Generated synthetic workout for %s on %s (watch forgotten, booking verified via %s)",
                    facility,
                    start_dt.strftime("%Y-%m-%d %H:%M"),
                    "+".join(sources)
                )

        return fused_workouts
