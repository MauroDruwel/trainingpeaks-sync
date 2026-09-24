"""
PDF Training Plan Parser and Client.
Parses swimming training schedules/plans from PDF files, extracting total meters,
dates, session goals, and structured sets (warmup, main set, cooldown).
"""
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ..models import PdfTrainingSession

logger = logging.getLogger(__name__)


# Dutch & English month mapping
MONTH_MAP = {
    "januari": 1, "january": 1, "jan": 1,
    "februari": 2, "february": 2, "feb": 2,
    "maart": 3, "march": 3, "mrt": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6,
    "juli": 7, "july": 7, "jul": 7,
    "augustus": 8, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


class TrainingPdfParser:
    """Extracts swimming training plans and total meters from PDF documents."""

    @staticmethod
    def extract_text_from_pdf(pdf_path: Path) -> str:
        """Extract plain text from all pages in a PDF."""
        pdf_path = Path(pdf_path)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            pages_text = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(text)
            return "\n\n".join(pages_text)
        except Exception as err:
            logger.warning("pypdf extraction failed for %s: %s", pdf_path.name, err)
            # Fallback: try raw string extraction if file is text-based
            try:
                with open(pdf_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except Exception:
                return ""

    @classmethod
    def parse_pdf(cls, pdf_path: Path) -> List[PdfTrainingSession]:
        """Parse a PDF file and return one or more training sessions."""
        text = cls.extract_text_from_pdf(pdf_path)
        if not text.strip():
            logger.warning("No readable text found in PDF: %s", pdf_path.name)
            return []

        # Some PDFs contain multiple sessions (split by headers/dates) or a single session
        sessions = cls._split_into_sessions(text, pdf_path)
        return sessions

    @classmethod
    def _split_into_sessions(cls, text: str, pdf_path: Path) -> List[PdfTrainingSession]:
        """Split text into training sessions if multiple exist, otherwise parse as single session."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Try to identify multi-session delimiters (e.g. repeated date headers or "Training 1", "Sessie 2")
        session_blocks: List[Tuple[Optional[datetime], List[str]]] = []
        current_date = cls.extract_date(text, filename=pdf_path.name)
        current_lines = []

        for line in lines:
            line_date = cls._extract_date_from_line(line)
            if line_date and current_lines:
                session_blocks.append((current_date, current_lines))
                current_date = line_date
                current_lines = [line]
            else:
                if line_date and not current_date:
                    current_date = line_date
                current_lines.append(line)

        if current_lines:
            session_blocks.append((current_date, current_lines))

        if not session_blocks:
            session_blocks = [(current_date, lines)]

        sessions = []
        for idx, (dt, block_lines) in enumerate(session_blocks):
            block_text = "\n".join(block_lines)
            distance = cls.extract_total_distance(block_text)
            title = cls.extract_title(block_lines, default=f"Swim Training ({pdf_path.stem})")
            session_id = f"pdf_{pdf_path.stem}_{dt.strftime('%Y%m%d') if dt else idx}"

            sessions.append(
                PdfTrainingSession(
                    session_id=session_id,
                    date=dt,
                    title=title,
                    total_distance_meters=distance,
                    content=block_text,
                    source_file=pdf_path.name,
                    sets=block_lines,
                )
            )

        return sessions

    @classmethod
    def extract_total_distance(cls, text: str, default: float = 4500.0) -> float:
        """
        Extract total swimming distance in meters.
        Matches patterns like:
        - "Totaal: 4500m", "Totaal: 4.500m", "Total: 4,500m"
        - "Afstand: 4.5 km", "Distance: 4500"
        - "Volume: 4500m"
        - Trailing "4500m" / "4500 m"
        """
        # 1. Explicit keyword match
        kw_patterns = [
            r"(?i)(?:totaal|total|volume|afstand|distance|tot)\s*[:=]?\s*([0-9.,]+)\s*(km|meter|m)?\b",
            r"(?i)\b([0-9.,]+)\s*(?:km|meter|m)\s*(?:in\s*totaal|total|volume)",
        ]
        for pat in kw_patterns:
            matches = re.findall(pat, text)
            for match in reversed(matches):
                val_str = match[0] if isinstance(match, tuple) else match
                unit = match[1].lower() if isinstance(match, tuple) and len(match) > 1 else ""
                parsed = cls._parse_numeric_distance(val_str, unit)
                if parsed and parsed >= 100:
                    return parsed

        # 2. Standalone large meter pattern at bottom/summary
        m_pattern = r"\b([1-9][0-9]{3,4})\s*(?:m|meter)\b"
        matches = re.findall(m_pattern, text, re.IGNORECASE)
        if matches:
            # Usually the largest or the last one is the session total
            candidates = [float(m) for m in matches if float(m) >= 500]
            if candidates:
                return candidates[-1]

        # 3. Summing set distances (e.g. 400 + 4x100 + 10x200)
        calculated = cls._sum_subsets(text)
        if calculated >= 500:
            return calculated

        return default

    @staticmethod
    def _parse_numeric_distance(val_str: str, unit: str = "") -> Optional[float]:
        """Convert string distance like '4.500', '4,5', '4500' to float meters."""
        cleaned = val_str.replace(" ", "").strip()
        if not cleaned:
            return None

        # Check for km
        is_km = "km" in unit.lower() or ("." in cleaned and float(cleaned.replace(",", ".")) < 30)

        # Dutch/European thousands separator e.g. 4.500 or 4,500
        if re.match(r"^\d{1,2}[.,]\d{3}$", cleaned):
            return float(re.sub(r"[.,]", "", cleaned))

        # Decimal km e.g. 4.5 km or 4,5 km
        if is_km:
            cleaned = cleaned.replace(",", ".")
            try:
                return float(cleaned) * 1000.0
            except ValueError:
                return None

        # Standard meters
        cleaned = re.sub(r"[^\d.]", "", cleaned)
        try:
            val = float(cleaned)
            return val
        except ValueError:
            return None

    @classmethod
    def _sum_subsets(cls, text: str) -> float:
        """Sum sets matching e.g. '10 x 100m' or '400m'."""
        total = 0.0
        # Multiplier pattern: 4x100m or 4 x 100 m
        mult_matches = re.findall(r"\b(\d+)\s*[xX*]\s*(\d+)\s*(?:m|meter)?\b", text)
        for count, dist in mult_matches:
            total += int(count) * int(dist)

        # Single distances: e.g. 400m inzwemmen
        single_matches = re.findall(r"\b(\d+)\s*(?:m|meter)\b", text)
        for dist in single_matches:
            # avoid double counting if already in mult
            val = int(dist)
            if val not in [int(d) for _, d in mult_matches]:
                total += val

        return total

    @classmethod
    def extract_date(cls, text: str, filename: str = "") -> Optional[datetime]:
        """Extract session date from text or filename."""
        # 1. Check filename first e.g. 2026-09-21, 20260921, swim_20260921.pdf
        fn_match = re.search(r"(?<!\d)(202\d)[-_]?(0[1-9]|1[0-2])[-_]?([0-3]\d)(?!\d)", filename)
        if fn_match:
            try:
                y, m, d = int(fn_match.group(1)), int(fn_match.group(2)), int(fn_match.group(3))
                return datetime(y, m, d, tzinfo=timezone.utc)
            except ValueError:
                pass

        # 2. Check each line of text
        for line in text.splitlines():
            d = cls._extract_date_from_line(line)
            if d:
                return d

        return None

    @classmethod
    def _extract_date_from_line(cls, line: str) -> Optional[datetime]:
        """Attempt to extract a date from a single line."""
        # ISO: YYYY-MM-DD
        m = re.search(r"\b(202\d)-(0[1-9]|1[0-2])-([0-3]\d)\b", line)
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)

        # European: DD/MM/YYYY or DD-MM-YYYY
        m = re.search(r"\b([0-3]?\d)[./-](0?[1-9]|1[0-2])[./-](202\d)\b", line)
        if m:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=timezone.utc)

        # Textual Dutch / English: e.g. "21 september 2026" or "Monday 21 September"
        for month_name, month_num in MONTH_MAP.items():
            pattern = rf"\b([0-3]?\d)\s+{month_name}(?:\s+(202\d))?\b"
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                day = int(m.group(1))
                year = int(m.group(2)) if m.group(2) else datetime.now(timezone.utc).year
                try:
                    return datetime(year, month_num, day, tzinfo=timezone.utc)
                except ValueError:
                    continue

        return None

    @staticmethod
    def extract_title(lines: List[str], default: str = "Swim Training") -> str:
        """Extract a suitable title for the training session."""
        for line in lines[:5]:
            clean = line.strip()
            if len(clean) > 3 and not re.match(r"^[0-9.:/-]+$", clean):
                if any(w in clean.lower() for w in ["training", "swim", "zwemmen", "sessie", "workout"]):
                    return f"🏊 {clean}"
        return default


class TrainingPdfClient:
    """Client for discovering and loading PDF training plans from disk."""

    def __init__(self, directory: Optional[Path] = None, file_path: Optional[Path] = None):
        self.directory = Path(directory) if directory else Path("trainings")
        self.file_path = Path(file_path) if file_path else None

    def is_configured(self) -> bool:
        """Check if PDF directory or specific file exists."""
        return bool(
            (self.file_path and self.file_path.exists())
            or (self.directory and self.directory.exists())
        )

    def fetch_trainings(self) -> List[PdfTrainingSession]:
        """Discover and parse all available PDF training plans."""
        files_to_parse: List[Path] = []

        if self.file_path and self.file_path.is_file():
            files_to_parse.append(self.file_path)

        if self.directory and self.directory.is_dir():
            for p in sorted(self.directory.glob("**/*.pdf")):
                if p not in files_to_parse:
                    files_to_parse.append(p)

        if not files_to_parse:
            logger.debug("No PDF training files found in %s", self.directory)
            return []

        all_sessions: List[PdfTrainingSession] = []
        for pdf_file in files_to_parse:
            try:
                logger.info("Parsing PDF training plan: %s", pdf_file.name)
                sessions = TrainingPdfParser.parse_pdf(pdf_file)
                all_sessions.extend(sessions)
                logger.info("Extracted %d session(s) from %s", len(sessions), pdf_file.name)
            except Exception as err:
                logger.warning("Failed to parse training PDF %s: %s", pdf_file.name, err)

        return all_sessions
