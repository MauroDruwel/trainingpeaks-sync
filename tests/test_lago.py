"""
Unit tests for LAGO email parser and IMAP client.
"""
import email
from email.message import EmailMessage
import tempfile
import unittest
from datetime import date, time as dtime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import LagoConfig
from src.sources.lago import LagoEmailParser, LagoIMAPClient


class TestLagoEmailParser(unittest.TestCase):
    """Test parsing LAGO reservation confirmation emails."""

    def test_parse_dutch_lago_confirmation_text(self):
        msg = EmailMessage()
        msg["Subject"] = "Bevestiging reservatie LAGO Gent Rozebroeken"
        msg["From"] = "reservaties@lago.be"
        msg["To"] = "swimming@maurodruwel.be"
        msg.set_content("""
Beste Mauro,

Bedankt voor je reservatie bij LAGO Gent Rozebroeken!
Hieronder vind je de details van je boeking:

- Datum: 23 september 2026
- Tijdslot: 07:00 - 08:30
- Activiteit: Baantjeszwemmen Sportbad 50m
- Reservatienummer: LAGO-987654

Vergeet je zwemkledij en ticket niet!
Tot binnenkort in het zwembad!
""")

        reservation = LagoEmailParser.parse_email_message(msg)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.source, "lago")
        self.assertEqual(reservation.reservation_id, "LAGO-987654")
        self.assertEqual(reservation.facility, "LAGO Gent Rozebroeken")
        self.assertEqual(reservation.start_time.date(), date(2026, 9, 23))
        self.assertEqual(reservation.start_time.time(), dtime(7, 0))
        self.assertEqual(reservation.end_time.time(), dtime(8, 30))
        self.assertEqual(reservation.duration_seconds, 5400)

    def test_parse_numeric_date_and_timeslot(self):
        msg = EmailMessage()
        msg["Subject"] = "LAGO Reservatie Sportbad"
        msg["From"] = "noreply@lago.be"
        msg["To"] = "swimming@maurodruwel.be"
        msg.set_content("""
Bevestiging van je reservering:
Datum: 15/10/2026
Uur: 12:00 tot 13:30
Locatie: LAGO Kortrijk Weide
Ticket: 112233
""")

        reservation = LagoEmailParser.parse_email_message(msg)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.reservation_id, "112233")
        self.assertEqual(reservation.facility, "LAGO Kortrijk Weide")
        self.assertEqual(reservation.start_time.date(), date(2026, 10, 15))
        self.assertEqual(reservation.start_time.time(), dtime(12, 0))
        self.assertEqual(reservation.end_time.time(), dtime(13, 30))

    def test_ignore_non_lago_email(self):
        msg = EmailMessage()
        msg["Subject"] = "Your weekly newsletter"
        msg["From"] = "news@example.com"
        msg["To"] = "someone@example.com"
        msg.set_content("Check out the latest tech news.")

        reservation = LagoEmailParser.parse_email_message(msg)
        self.assertIsNone(reservation)

    def test_parse_eml_file(self):
        with tempfile.NamedTemporaryFile(suffix=".eml", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            msg = EmailMessage()
            msg["Subject"] = "Bevestiging LAGO baantjeszwemmen"
            msg["From"] = "noreply@lago.be"
            msg["To"] = "swimming@maurodruwel.be"
            msg.set_content("Datum: 01/11/2026\nTijd: 08:00 - 09:00\nReservatie: 556677\nLocatie: Sportbad")
            tmp.write(msg.as_bytes())

        try:
            reservation = LagoEmailParser.parse_eml_file(tmp_path)
            self.assertIsNotNone(reservation)
            self.assertEqual(reservation.reservation_id, "556677")
            self.assertEqual(reservation.start_time.date(), date(2026, 11, 1))
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


class TestLagoIMAPClient(unittest.TestCase):
    """Test IMAP fetching and offline sample directory."""

    def test_fetch_from_sample_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sample_path = Path(temp_dir)
            eml_file = sample_path / "lago_booking.eml"

            msg = EmailMessage()
            msg["Subject"] = "Bevestiging reservatie LAGO Rozebroeken"
            msg["From"] = "noreply@lago.be"
            msg.set_content("Datum: 25/12/2026 om 09:00 - 10:30\nTicket #998877")
            with open(eml_file, "wb") as f:
                f.write(msg.as_bytes())

            config = LagoConfig(sample_dir=sample_path)
            client = LagoIMAPClient(config)
            reservations = client.fetch_reservations()

            self.assertEqual(len(reservations), 1)
            self.assertEqual(reservations[0].reservation_id, "998877")

    def test_fetch_unconfigured_returns_empty(self):
        config = LagoConfig()
        client = LagoIMAPClient(config)
        self.assertEqual(client.fetch_reservations(), [])
