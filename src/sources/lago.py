"""
LAGO Swimming Reservation Parser and IMAP Client.
Retrieves and parses reservation emails sent to swimming@maurodruwel.be.
"""
import email
from email import policy
import imaplib
import logging
import re
from datetime import datetime, date, time as dtime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..config import LagoConfig
from ..models import SwimReservation


logger = logging.getLogger(__name__)

# Common Dutch/Flemish month names mapping
DUTCH_MONTHS = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2,
    "maart": 3, "mrt": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "augustus": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class LagoEmailParser:
    """Parses LAGO confirmation emails into structured SwimReservation models."""

    @staticmethod
    def parse_eml_file(file_path: Path) -> Optional[SwimReservation]:
        """Parse an .eml email file from disk."""
        try:
            with open(file_path, "rb") as f:
                msg = email.message_from_binary_file(f, policy=policy.default)
                return LagoEmailParser.parse_email_message(msg)
        except Exception as err:
            logger.error("Failed to parse EML file %s: %s", file_path, err)
            return None

    @staticmethod
    def parse_raw_email(raw_bytes: bytes) -> Optional[SwimReservation]:
        """Parse raw email RFC822 bytes."""
        try:
            msg = email.message_from_bytes(raw_bytes, policy=policy.default)
            return LagoEmailParser.parse_email_message(msg)
        except Exception as err:
            logger.error("Failed to parse raw email bytes: %s", err)
            return None

    @classmethod
    def parse_email_message(cls, msg: email.message.EmailMessage) -> Optional[SwimReservation]:
        """Extract reservation metadata from an EmailMessage."""
        subject = str(msg.get("Subject", ""))
        sender = str(msg.get("From", ""))
        to = str(msg.get("To", ""))

        # Check if email is LAGO related
        is_lago = (
            "lago" in subject.lower()
            or "lago" in sender.lower()
            or "zwembad" in subject.lower()
            or "sportbad" in subject.lower()
            or "baantjeszwemmen" in subject.lower()
            or "swimming@maurodruwel.be" in to.lower()
        )
        if not is_lago:
            logger.debug("Email is not LAGO related (Subject: %s)", subject)
            return None

        # Extract email body (plain text or html)
        body_text = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ("text/plain", "text/html"):
                    try:
                        content = part.get_content()
                        body_text += " " + str(content)
                    except Exception:
                        pass
        else:
            body_text = str(msg.get_content())

        # Clean HTML tags if present
        plain_text = re.sub(r"<[^>]+>", " ", body_text)
        full_text = f"{subject}\n{plain_text}"

        # 1. Extract Date
        session_date = cls._extract_date(full_text)
        if not session_date:
            # Fallback to email sent date if body has no explicit date
            email_date_hdr = msg.get("Date")
            if email_date_hdr:
                try:
                    dt = email.utils.parsedate_to_datetime(email_date_hdr)
                    session_date = dt.date()
                except Exception:
                    session_date = date.today()
            else:
                session_date = date.today()

        # 2. Extract Time Slot (e.g., 07:00 - 08:30 or 07:00 tot 08:30)
        start_time_val, end_time_val = cls._extract_time_slot(full_text)

        start_dt = datetime.combine(session_date, start_time_val).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(session_date, end_time_val).replace(tzinfo=timezone.utc) if end_time_val else None

        duration_sec = int((end_dt - start_dt).total_seconds()) if end_dt else 3600

        # 3. Extract Reservation Reference
        res_id = cls._extract_reservation_id(full_text)
        if not res_id:
            res_id = f"lago_{session_date.strftime('%Y%m%d')}_{start_time_val.strftime('%H%M')}"

        # 4. Extract Facility / Pool name
        facility = cls._extract_facility(full_text)

        return SwimReservation(
            source="lago",
            reservation_id=res_id,
            title=f"LAGO Swim ({facility})",
            facility=facility,
            start_time=start_dt,
            end_time=end_dt,
            duration_seconds=duration_sec,
            raw_details={
                "subject": subject,
                "sender": sender,
                "extracted_id": res_id,
                "raw_text_snippet": plain_text[:300].strip(),
            },
        )

    @classmethod
    def _extract_date(cls, text: str) -> Optional[date]:
        """Extract reservation date from Dutch or ISO formatted text."""
        # 1. DD/MM/YYYY or DD-MM-YYYY
        m_num = re.search(r"\b([0-3]?[0-9])[/\-.]([0-1]?[0-9])[/\-.](202[0-9])\b", text)
        if m_num:
            day, month, year = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                pass

        # 2. YYYY-MM-DD
        m_iso = re.search(r"\b(202[0-9])-([0-1]?[0-9])-([0-3]?[0-9])\b", text)
        if m_iso:
            year, month, day = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                pass

        # 3. Dutch text date: e.g. "23 september 2026" or "woensdag 23 september"
        for month_name, month_num in DUTCH_MONTHS.items():
            pattern = rf"\b([0-3]?[0-9])\s+{month_name}\s*(202[0-9])?\b"
            m_dutch = re.search(pattern, text, re.IGNORECASE)
            if m_dutch:
                day = int(m_dutch.group(1))
                year = int(m_dutch.group(2)) if m_dutch.group(2) else date.today().year
                try:
                    return date(year, month_num, day)
                except ValueError:
                    pass

        return None

    @classmethod
    def _extract_time_slot(cls, text: str) -> tuple[dtime, Optional[dtime]]:
        """Extract start time and end time from text."""
        # Search for pattern: HH:MM - HH:MM or HH:MM tot HH:MM
        m_slot = re.search(
            r"\b([0-2]?[0-9]):([0-5][0-9])\s*(?:-|tot|–|to)\s*([0-2]?[0-9]):([0-5][0-9])\b",
            text,
            re.IGNORECASE
        )
        if m_slot:
            sh, sm, eh, em = (
                int(m_slot.group(1)),
                int(m_slot.group(2)),
                int(m_slot.group(3)),
                int(m_slot.group(4)),
            )
            return dtime(sh, sm), dtime(eh, em)

        # Single time: e.g. "om 07:00" or "start: 07:00"
        m_single = re.search(r"\b([0-2]?[0-9]):([0-5][0-9])\b", text)
        if m_single:
            sh, sm = int(m_single.group(1)), int(m_single.group(2))
            end_h = (sh + 1) % 24
            return dtime(sh, sm), dtime(end_h, sm)

        return dtime(7, 0), dtime(8, 0)

    @classmethod
    def _extract_reservation_id(cls, text: str) -> Optional[str]:
        """Extract reservation reference or ticket number."""
        patterns = [
            r"(?:reservatienummer|ticketnummer|boekingsnummer|referentie|booking(?:\s*id)?)\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9\-]+)",
            r"(?:ticket|reservatie|boeking)\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9\-]+)",
            r"(?:ticket|reservatie|booking)\s+#([A-Za-z0-9][A-Za-z0-9\-]+)",
            r"(?:reservatienummer|ticketnummer)\s+([A-Za-z0-9][A-Za-z0-9\-]+)",
        ]
        stopwords = {"lago", "sportbad", "zwembad", "gent", "kortrijk", "rozebroeken", "bevestiging", "sport"}
        for pat in patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                val = m.group(1).strip()
                if val.lower() not in stopwords and len(val) >= 3:
                    return val
        return None

    @classmethod
    def _extract_facility(cls, text: str) -> str:
        """Extract specific LAGO location / pool facility."""
        text_lower = text.lower()
        if "rozebroeken" in text_lower:
            return "LAGO Gent Rozebroeken"
        elif "kortrijk" in text_lower:
            return "LAGO Kortrijk Weide"
        elif "sint-truiden" in text_lower or "bloesembad" in text_lower:
            return "LAGO Sint-Truiden Bloesembad"
        elif "berchem" in text_lower or "deurne" in text_lower:
            return "LAGO Club Antwerpen"
        elif "sportbad" in text_lower or "50m" in text_lower:
            return "LAGO Sportbad 50m"
        elif "lago" in text_lower:
            return "LAGO Zwembad"
        return "LAGO Pool"


class LagoIMAPClient:
    """Connects to IMAP server to fetch and parse LAGO reservation emails."""

    def __init__(self, config: LagoConfig):
        self.config = config

    def fetch_reservations(self) -> List[SwimReservation]:
        """Fetch reservations from local sample directory or remote IMAP mailbox."""
        reservations: List[SwimReservation] = []

        # 1. Offline / Sample files check (for tests or local file ingestion)
        if self.config.sample_dir and self.config.sample_dir.is_dir():
            for eml_file in self.config.sample_dir.glob("*.eml"):
                res = LagoEmailParser.parse_eml_file(eml_file)
                if res:
                    reservations.append(res)
            if reservations:
                logger.info("Found %d LAGO reservations from local sample directory", len(reservations))
                return reservations

        # 2. Remote IMAP connection
        if not (self.config.imap_server and self.config.imap_user and self.config.imap_password):
            logger.debug("LAGO IMAP credentials not fully configured.")
            return reservations

        try:
            logger.info("Connecting to IMAP server %s as %s...", self.config.imap_server, self.config.imap_user)
            mail = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port)
            mail.login(self.config.imap_user, self.config.imap_password)
            mail.select(self.config.mailbox, readonly=True)

            # Search for LAGO emails (or subject containing 'reservatie' / 'LAGO')
            search_queries = [
                '(OR (FROM "lago") (SUBJECT "LAGO"))',
                '(SUBJECT "reservatie")',
                'ALL'
            ]

            msg_ids = []
            for query in search_queries:
                status, data = mail.search(None, query)
                if status == "OK" and data[0]:
                    msg_ids = data[0].split()
                    break

            # Process up to last 20 messages to keep check fast
            for msg_id in reversed(msg_ids[-20:]):
                status, msg_data = mail.fetch(msg_id, '(RFC822)')
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_email = msg_data[0][1]
                reservation = LagoEmailParser.parse_raw_email(raw_email)
                if reservation:
                    reservations.append(reservation)

            mail.close()
            mail.logout()
            logger.info("Retrieved %d LAGO reservations via IMAP.", len(reservations))

        except Exception as err:
            logger.error("Failed to fetch LAGO reservations via IMAP: %s", err)

        return reservations
