"""
Unit tests for TrainingPeaksEmailUploader.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.config import SyncConfig
from src.sync.email import TrainingPeaksEmailUploader


class TestEmailUploader(unittest.TestCase):
    """Test automated TrainingPeaks email upload."""

    def test_can_send(self):
        cfg = SyncConfig()
        uploader = TrainingPeaksEmailUploader(cfg)
        self.assertFalse(uploader.can_send())

        cfg.tp_email = "mauro.upload@trainingpeaks.com"
        cfg.smtp_host = "smtp.gmail.com"
        cfg.smtp_user = "user@gmail.com"
        cfg.smtp_password = "app-password"
        self.assertTrue(uploader.can_send())

    def test_send_tcx_file_not_found(self):
        cfg = SyncConfig(
            tp_email="mauro.upload@trainingpeaks.com",
            smtp_host="smtp.gmail.com",
            smtp_user="user@gmail.com",
            smtp_password="app-password"
        )
        uploader = TrainingPeaksEmailUploader(cfg)
        result = uploader.send_tcx(Path("/non/existent/path.tcx"))
        self.assertFalse(result)

    def test_send_tcx_success(self):
        cfg = SyncConfig(
            tp_email="mauro.upload@trainingpeaks.com",
            smtp_host="smtp.gmail.com",
            smtp_user="user@gmail.com",
            smtp_password="app-password"
        )
        uploader = TrainingPeaksEmailUploader(cfg)

        with tempfile.NamedTemporaryFile(suffix=".tcx") as tmp:
            tmp.write(b"<TCX>sample</TCX>")
            tmp.flush()

            mock_smtp_instance = MagicMock()
            mock_smtp_cm = MagicMock()
            mock_smtp_cm.__enter__.return_value = mock_smtp_instance

            with patch("smtplib.SMTP", return_value=mock_smtp_cm) as mock_smtp_cls:
                result = uploader.send_tcx(Path(tmp.name), subject="Test Workout")
                self.assertTrue(result)
                mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
                mock_smtp_instance.starttls.assert_called_once()
                mock_smtp_instance.login.assert_called_once_with("user@gmail.com", "app-password")
                mock_smtp_instance.send_message.assert_called_once()
