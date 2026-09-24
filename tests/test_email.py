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

    def test_send_tcx_ssl_465(self):
        cfg = SyncConfig(
            tp_email="mauro.upload@trainingpeaks.com",
            smtp_host="mailserver.maurodruwel.be",
            smtp_port=465,
            smtp_user="sports@maurodruwel.be",
            smtp_password="app-password",
        )
        uploader = TrainingPeaksEmailUploader(cfg)

        with tempfile.NamedTemporaryFile(suffix=".tcx") as tmp:
            tmp.write(b"<TCX>sample</TCX>")
            tmp.flush()

            mock_ssl_instance = MagicMock()
            mock_ssl_cm = MagicMock()
            mock_ssl_cm.__enter__.return_value = mock_ssl_instance

            with patch("smtplib.SMTP_SSL", return_value=mock_ssl_cm) as mock_ssl_cls:
                result = uploader.send_tcx(Path(tmp.name), subject="Test SSL Workout")
                self.assertTrue(result)
                mock_ssl_cls.assert_called_once_with("mailserver.maurodruwel.be", 465, timeout=30)
                mock_ssl_instance.login.assert_called_once_with("sports@maurodruwel.be", "app-password")
                mock_ssl_instance.send_message.assert_called_once()

    def test_test_connection_not_configured(self):
        cfg = SyncConfig()
        uploader = TrainingPeaksEmailUploader(cfg)
        ok, msg = uploader.test_connection()
        self.assertFalse(ok)
        self.assertIn("TP_EMAIL is not set", msg)

    def test_test_connection_success(self):
        cfg = SyncConfig(
            tp_email="mauro.upload@trainingpeaks.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="sports@maurodruwel.be",
            smtp_password="secretpassword",
        )
        uploader = TrainingPeaksEmailUploader(cfg)

        mock_smtp_instance = MagicMock()
        mock_smtp_cm = MagicMock()
        mock_smtp_cm.__enter__.return_value = mock_smtp_instance

        with patch("smtplib.SMTP", return_value=mock_smtp_cm):
            ok, msg = uploader.test_connection()
            self.assertTrue(ok)
            self.assertIn("Successfully authenticated", msg)
            mock_smtp_instance.starttls.assert_called_once()
            mock_smtp_instance.login.assert_called_once_with("sports@maurodruwel.be", "secretpassword")
