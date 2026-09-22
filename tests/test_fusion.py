"""
Unit tests for multi-source WorkoutReconciler and fusion engine.
"""
import unittest
from datetime import datetime, timezone

from src.config import FusionConfig
from src.fusion.reconciler import WorkoutReconciler
from src.models import Sport, ActivitySummary, SwimReservation


class TestWorkoutReconciler(unittest.TestCase):
    """Test correlation and synthetic workout generation across multiple sources."""

    def test_reconcile_with_watch_and_reservations(self):
        # Athlete went swimming, reserved both LAGO and StudentApp, and recorded on watch!
        time_slot = datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc)

        strava_swim = ActivitySummary(
            id=12345,
            name="Morning Swim Session",
            sport=Sport.SWIM,
            strava_type="Swim",
            start_date="2026-09-23T07:05:00Z",
            distance_meters=2500,
            elapsed_time_seconds=3600
        )

        lago_res = SwimReservation(
            source="lago",
            reservation_id="LAGO-100",
            title="LAGO Gent Rozebroeken",
            facility="LAGO Gent Rozebroeken",
            start_time=time_slot,
            duration_seconds=5400
        )

        student_res = SwimReservation(
            source="studentapp",
            reservation_id="STUD-200",
            title="GUSB Pool",
            facility="GUSB Pool",
            start_time=time_slot,
            duration_seconds=5400
        )

        reconciler = WorkoutReconciler(FusionConfig(time_window_minutes=60))
        workouts = reconciler.reconcile(
            strava_activities=[strava_swim],
            lago_reservations=[lago_res],
            studentapp_reservations=[student_res]
        )

        self.assertEqual(len(workouts), 1)
        w = workouts[0]
        self.assertTrue(w.has_watch_data)
        self.assertIn("strava", w.sources)
        self.assertIn("lago", w.sources)
        self.assertIn("studentapp", w.sources)
        self.assertEqual(w.distance_meters, 2500)
        self.assertEqual(w.duration_seconds, 5400)  # Preserves full slot duration (5400s) even when watch recorded 3600s!
        self.assertIn("Full slot preserved", w.description)
        self.assertIn("LAGO-100", w.description)
        self.assertIn("STUD-200", w.description)

    def test_reconcile_when_athlete_forgot_watch(self):
        # Athlete went swimming with LAGO and StudentApp reservations, but forgot watch!
        time_slot = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

        lago_res = SwimReservation(
            source="lago",
            reservation_id="LAGO-FORGOTTEN-WATCH",
            title="LAGO Gent Rozebroeken",
            facility="LAGO Gent Rozebroeken",
            start_time=time_slot,
            duration_seconds=3600
        )

        reconciler = WorkoutReconciler(
            FusionConfig(
                auto_generate_synthetic_if_watch_forgotten=True,
                synthetic_swim_distance_meters=2200.0,
                synthetic_swim_duration_seconds=3600
            )
        )

        # No Strava activities!
        workouts = reconciler.reconcile(
            strava_activities=[],
            lago_reservations=[lago_res],
            studentapp_reservations=[]
        )

        self.assertEqual(len(workouts), 1)
        w = workouts[0]
        self.assertFalse(w.has_watch_data)  # Synthetic entry!
        self.assertIn("lago", w.sources)
        self.assertEqual(w.sport, Sport.SWIM)
        self.assertEqual(w.distance_meters, 2200.0)
        self.assertEqual(w.duration_seconds, 3600)
        self.assertIn("Watch Forgotten", w.description)

    def test_reconcile_standalone_strava_run(self):
        # Athlete did a morning run (no pool reservation)
        strava_run = ActivitySummary(
            id=9999,
            name="10k Tempo Run",
            sport=Sport.RUN,
            strava_type="Run",
            start_date="2026-09-25T06:00:00Z",
            distance_meters=10000,
            elapsed_time_seconds=2700
        )

        reconciler = WorkoutReconciler()
        workouts = reconciler.reconcile([strava_run], [], [])

        self.assertEqual(len(workouts), 1)
        self.assertEqual(workouts[0].sources, ["strava"])
        self.assertTrue(workouts[0].has_watch_data)
        self.assertEqual(workouts[0].sport, Sport.RUN)

    def test_reconcile_swim_preserves_full_slot_when_strava_cuts_off_time(self):
        # Strava recorded 45 mins (2700s) due to pool resting intervals, but default slot is 1h45m (6300s)
        strava_swim = ActivitySummary(
            id=5555,
            name="Afternoon Laps",
            sport=Sport.SWIM,
            strava_type="Swim",
            start_date="2026-09-22T14:00:00Z",
            distance_meters=2000,
            elapsed_time_seconds=2700,
            moving_time_seconds=2400,
        )

        reconciler = WorkoutReconciler(FusionConfig(synthetic_swim_duration_seconds=6300))
        workouts = reconciler.reconcile([strava_swim], [], [])

        self.assertEqual(len(workouts), 1)
        w = workouts[0]
        self.assertEqual(w.duration_seconds, 6300)  # Preserved full 1h45m slot!
        self.assertIn("Full slot preserved", w.description)

    def test_reconcile_swim_longer_than_slot_keeps_longer_time(self):
        # Athlete swam 2 hours (7200s), which is longer than the 1h45m (6300s) slot
        strava_swim = ActivitySummary(
            id=6666,
            name="Endurance Swim",
            sport=Sport.SWIM,
            strava_type="Swim",
            start_date="2026-09-22T14:00:00Z",
            distance_meters=4500,
            elapsed_time_seconds=7200,
            moving_time_seconds=6800,
        )

        reconciler = WorkoutReconciler(FusionConfig(synthetic_swim_duration_seconds=6300))
        workouts = reconciler.reconcile([strava_swim], [], [])

        self.assertEqual(len(workouts), 1)
        w = workouts[0]
        self.assertEqual(w.duration_seconds, 7200)  # Keeps full 2h!
