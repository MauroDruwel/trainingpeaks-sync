"""
Optional email dispatcher for direct TrainingPeaks upload.
TrainingPeaks allows users to email workout files (.tcx) to their personal upload address.
"""
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from ..config import SyncConfig


logger = logging.getLogger(__name__)


class TrainingPeaksEmailUploader:
    """Sends TCX workout files to athlete's TrainingPeaks email upload address."""

    def __init__(self, config: SyncConfig):
        self.config = config

    def can_send(self) -> bool:
        """Check if email upload is properly configured."""
        return self.config.is_email_upload_configured

    def send_tcx(self, tcx_path: Path, subject: Optional[str] = None) -> bool:
        """Send TCX file as an attachment via SMTP."""
        if not self.can_send():
            logger.debug("Email upload not fully configured, skipping email dispatch.")
            return False

        tcx_path = Path(tcx_path)
        if not tcx_path.is_file():
            logger.error("TCX file to email does not exist: %s", tcx_path)
            return False

        try:
            msg = EmailMessage()
            msg["Subject"] = subject or f"TrainingPeaks Sync: {tcx_path.stem}"
            msg["From"] = self.config.smtp_from or self.config.smtp_user
            msg["To"] = self.config.tp_email
            msg.set_content(f"Automated upload for workout file: {tcx_path.name}")

            with open(tcx_path, "rb") as f:
                file_data = f.read()
                msg.add_attachment(
                    file_data,
                    maintype="application",
                    subtype="vnd.garmin.tcx+xml",
                    filename=tcx_path.name,
                )

            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.config.smtp_user, self.config.smtp_password)
                server.send_message(msg)

            logger.info("Successfully emailed %s to TrainingPeaks (%s)", tcx_path.name, self.config.tp_email)
            return True

        except Exception as err:
            logger.error("Failed to email TCX file %s: %s", tcx_path, str(err))
            return False
