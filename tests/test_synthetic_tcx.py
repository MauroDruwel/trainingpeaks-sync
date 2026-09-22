"""
Unit tests for synthetic TCX generation.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.fusion.synthetic_tcx import generate_synthetic_swim_tcx
from src.models import FusedWorkout, Sport, SwimReservation
from src.tcx.formatter import validate_tcx_file


class TestSyntheticTCX(unittest.TestCase):
    """Test generating valid TrainingPeaks TCX files when watch is forgotten."""

    def test_generate_from_fused_workout(self):
        workout = FusedWorkout(
            session_id="synthetic_test_1",
            sport=Sport.SWIM,
            start_time=datetime(2026, 9, 23, 7, 0, tzinfo=timezone.utc),
            duration_seconds=3600,
            distance_meters=2000.0,
            sources=["lago", "studentapp"],
            has_watch_data=False,
            title="LAGO Gent Rozebroeken",
        )

        tcx_content = generate_synthetic_swim_tcx(workout=workout)
        self.assertIn('<Activity Sport="Other">', tcx_content)
        self.assertIn('<TotalTimeSeconds>3600</TotalTimeSeconds>', tcx_content)
        self.assertIn('<DistanceMeters>2000.0</DistanceMeters>', tcx_content)
        self.assertIn('<Trackpoint>', tcx_content)

        # Write to temporary file and validate with TCXReader
        with tempfile.NamedTemporaryFile(suffix=".tcx", mode="w", delete=False) as tmp:
            tmp.write(tcx_content)
            tmp_path = Path(tmp.name)

        try:
            is_valid, tcx_data = validate_tcx_file(str(tmp_path))
            self.assertTrue(is_valid)
            self.assertIsNotNone(tcx_data)
            self.assertEqual(tcx_data.distance, 2000)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_generate_from_reservation(self):
        res = SwimReservation(
            source="lago",
            reservation_id="REF-999",
            title="Sportbad 50m",
            facility="LAGO Gent Rozebroeken",
            start_time=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
            duration_seconds=5400,
        )

        tcx_content = generate_synthetic_swim_tcx(reservation=res, distance_meters=3000.0)
        self.assertIn('<DistanceMeters>3000.0</DistanceMeters>', tcx_content)
        self.assertIn('<TotalTimeSeconds>5400</TotalTimeSeconds>', tcx_content)
