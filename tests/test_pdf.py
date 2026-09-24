"""
Unit tests for PDF training plan parser and multi-source integration.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.models import (
    PdfTrainingSession,
    SwimReservation,
    Sport,
    ActivitySummary,
)
from src.sources.pdf import TrainingPdfParser, TrainingPdfClient
from src.fusion.reconciler import WorkoutReconciler
from src.config import FusionConfig


class TestTrainingPdfParser(unittest.TestCase):
    """Test PDF text extraction, distance parsing, and date detection."""

    def test_parse_numeric_distance(self):
        # Meters with dot or comma as thousands separator
        self.assertEqual(TrainingPdfParser._parse_numeric_distance("4.500", "m"), 4500.0)
        self.assertEqual(TrainingPdfParser._parse_numeric_distance("4,500", "meter"), 4500.0)
        self.assertEqual(TrainingPdfParser._parse_numeric_distance("5000", "m"), 5000.0)

        # Decimal km
        self.assertEqual(TrainingPdfParser._parse_numeric_distance("4.5", "km"), 4500.0)
        self.assertEqual(TrainingPdfParser._parse_numeric_distance("4,5", "km"), 4500.0)

    def test_extract_total_distance(self):
        text1 = """
        Zwemtraining A-Kern
        Datum: 21-09-2026
        Inzwemmen: 400m wissel
        Kern: 10 x 200m borstcrawl op 3:00
        Uitzwemmen: 200m
        Totaal: 4.500m
        """
        self.assertEqual(TrainingPdfParser.extract_total_distance(text1), 4500.0)

        text2 = """
        Swim Workout
        Date: 2026-09-22
        Main Set: 4 x 400m
        Total volume: 5000m
        """
        self.assertEqual(TrainingPdfParser.extract_total_distance(text2), 5000.0)

        text3 = """
        Afstand: 4.5 km
        """
        self.assertEqual(TrainingPdfParser.extract_total_distance(text3), 4500.0)

    def test_sum_subsets_fallback(self):
        text = """
        Inzwemmen: 400m
        Opdracht: 8 x 100m
        Uitzwemmen: 200m
        """
        # 400 + 800 + 200 = 1400
        dist = TrainingPdfParser.extract_total_distance(text)
        self.assertEqual(dist, 1400.0)

    def test_extract_date(self):
        self.assertEqual(
            TrainingPdfParser.extract_date("Training op 2026-09-21 in LAGO"),
            datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
        self.assertEqual(
            TrainingPdfParser.extract_date("Datum: 21/09/2026"),
            datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
        self.assertEqual(
            TrainingPdfParser.extract_date("Maandag 21 september 2026"),
            datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
        # From filename
        self.assertEqual(
            TrainingPdfParser.extract_date("", filename="swim_plan_20260921.pdf"),
            datetime(2026, 9, 21, tzinfo=timezone.utc),
        )

    def test_client_fetch_trainings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            dummy_pdf = tmp_path / "training_20260924.pdf"
            dummy_pdf.write_text("Dummy content")

            with patch.object(
                TrainingPdfParser,
                "parse_pdf",
                return_value=[
                    PdfTrainingSession(
                        session_id="pdf_1",
                        date=datetime(2026, 9, 24, tzinfo=timezone.utc),
                        title="🏊 Training A",
                        total_distance_meters=4800.0,
                        content="Warmup 400m, Main 4000m, Cooldown 400m",
                        source_file="training_20260924.pdf",
                    )
                ],
            ):
                client = TrainingPdfClient(directory=tmp_path)
                self.assertTrue(client.is_configured())
                sessions = client.fetch_trainings()
                self.assertEqual(len(sessions), 1)
                self.assertEqual(sessions[0].total_distance_meters, 4800.0)
                self.assertEqual(sessions[0].date_str, "2026-09-24")


class TestReconcilerWithPdf(unittest.TestCase):
    """Test WorkoutReconciler integration with PDF training plans."""

    def setUp(self):
        self.config = FusionConfig(
            time_window_minutes=90,
            synthetic_swim_distance_meters=4500.0,
            synthetic_swim_duration_seconds=6300,
        )
        self.reconciler = WorkoutReconciler(self.config)

    def test_reconcile_lago_with_pdf_matching(self):
        dt = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
        lago_res = SwimReservation(
            source="lago",
            reservation_id="LAGO-101",
            title="Sportbad 50m",
            facility="LAGO Kortrijk Weide",
            start_time=dt,
            duration_seconds=6300,
        )

        pdf_sess = PdfTrainingSession(
            session_id="pdf_plan_1",
            date=datetime(2026, 9, 21, tzinfo=timezone.utc),
            title="Wedstrijdtraining",
            total_distance_meters=5200.0,
            content="Total: 5200m",
            source_file="plan_sep21.pdf",
        )

        fused = self.reconciler.reconcile(
            strava_activities=[],
            lago_reservations=[lago_res],
            studentapp_reservations=[],
            pdf_trainings=[pdf_sess],
        )

        self.assertEqual(len(fused), 1)
        workout = fused[0]
        self.assertIn("lago", workout.sources)
        self.assertIn("pdf", workout.sources)
        # Distance should match the exact PDF plan (5200m) rather than default 4500m!
        self.assertEqual(workout.distance_meters, 5200.0)
        self.assertIn("plan_sep21.pdf", workout.description)
        self.assertIn("5200m", workout.description)

    def test_reconcile_default_swim_distance_4500m(self):
        dt = datetime(2026, 9, 22, 8, 30, tzinfo=timezone.utc)
        lago_res = SwimReservation(
            source="lago",
            reservation_id="LAGO-102",
            title="Sportbad 50m",
            facility="LAGO Kortrijk Weide",
            start_time=dt,
            duration_seconds=6300,
        )

        fused = self.reconciler.reconcile(
            strava_activities=[],
            lago_reservations=[lago_res],
            studentapp_reservations=[],
            pdf_trainings=[],
        )

        self.assertEqual(len(fused), 1)
        workout = fused[0]
        # Distance should default to 4500m
        self.assertEqual(workout.distance_meters, 4500.0)

    def test_standalone_pdf_training(self):
        pdf_sess = PdfTrainingSession(
            session_id="pdf_plan_standalone",
            date=datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc),
            title="Speed Workout",
            total_distance_meters=4600.0,
            content="Warmup 600m...",
            source_file="friday_speed.pdf",
        )

        fused = self.reconciler.reconcile(
            strava_activities=[],
            lago_reservations=[],
            studentapp_reservations=[],
            pdf_trainings=[pdf_sess],
        )

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0].sources, ["pdf"])
        self.assertEqual(fused[0].distance_meters, 4600.0)
