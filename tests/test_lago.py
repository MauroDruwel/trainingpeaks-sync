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

    def test_ignore_trainingpeaks_system_email(self):
        msg = EmailMessage()
        msg["Subject"] = "Welcome Athlete, You're Now a TrainingPeaks Athlete!"
        msg["From"] = "info@email.trainingpeaks.com"
        msg["To"] = "swimming@maurodruwel.be"
        msg.set_content("Welcome to TrainingPeaks, Mauro!")

        reservation = LagoEmailParser.parse_email_message(msg)
        self.assertIsNone(reservation)

    def test_parse_forwarded_lago_email_with_pdf_attachment(self):
        import zlib
        msg = EmailMessage()
        msg["Subject"] = "Fwd: Dank je wel voor je aankoop!"
        msg["From"] = "Mauro Druwel <mauro.druwel@gmail.com>"
        msg["To"] = "swimming@maurodruwel.be"
        msg.set_content("""
Ingelmunster
---------- Forwarded message ---------
Van: <kortrijkweide@lago.be>
Subject: Dank je wel voor je aankoop!
[image: barcode] 89209761305197092000
LAGO Kortrijk Weide: tickets sportbad
""")
        # Create a synthetic PDF payload with compressed stream
        stream_content = b"""
BT
/FAAAAJ 9 Tf
[(LAGO Kortrijk W)-1(eid)1(e)-1(: t)1(icke)-1(ts)1( )-1(s)1(portb)1(ad)] TJ
ET
BT
/FAAABE 9 Tf
[(Rese)1(rv)1(ati)-1(enummer)1(:)-2206(217)1(23594)] TJ
ET
BT
/FAAABE 9 Tf
[(Datu)-1(m)1( z)-1(w)1(embeurt:)-2353(22-9-20)1(26 08:)1(30:0)1(0)] TJ
ET
"""
        compressed = zlib.compress(stream_content)
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length 123 >>\nstream\r\n" + compressed + b"\r\nendstream\nendobj\n%%EOF"

        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename="Reserveringsbewijs.pdf"
        )

        reservation = LagoEmailParser.parse_email_message(msg)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.reservation_id, "21723594")
        self.assertEqual(reservation.facility, "LAGO Kortrijk Weide")
        self.assertEqual(reservation.start_time.date(), date(2026, 9, 22))
        self.assertEqual(reservation.start_time.hour, 8)
        self.assertEqual(reservation.start_time.minute, 30)
        self.assertEqual(reservation.duration_seconds, 3600)
        self.assertEqual(reservation.raw_details.get("barcode"), "89209761305197092000")


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
