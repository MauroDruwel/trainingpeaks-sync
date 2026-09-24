"""
Unit tests for configuration loader and models.
"""
import os
import unittest
from unittest.mock import patch
from pathlib import Path

from src.config import AppConfig, StravaConfig, AIConfig, SyncConfig


class TestConfig(unittest.TestCase):
    """Test configuration loading and properties."""

    def test_strava_config_properties(self):
        cfg = StravaConfig()
        self.assertFalse(cfg.is_oauth_configured)
        self.assertFalse(cfg.is_headless_configured)

        cfg.client_id = "12345"
        cfg.client_secret = "secret"
        self.assertTrue(cfg.is_oauth_configured)
        self.assertFalse(cfg.is_headless_configured)

        cfg.refresh_token = "refreshtok"
        self.assertTrue(cfg.is_headless_configured)

    def test_ai_config_effective_api_key(self):
        # Empty case
        cfg = AIConfig()
        self.assertEqual(cfg.effective_api_key, "")

        # Key explicitly set
        cfg.api_key = "my-secret-key"
        self.assertEqual(cfg.effective_api_key, "my-secret-key")

        # Localhost base_url without key -> dummy key
        cfg.api_key = None
        cfg.base_url = "http://localhost:11434/v1"
        self.assertEqual(cfg.effective_api_key, "dummy-local-key")

    def test_sync_config_email_properties(self):
        cfg = SyncConfig()
        self.assertFalse(cfg.is_email_upload_configured)

        cfg.tp_email = "athlete.upload@trainingpeaks.com"
        cfg.smtp_host = "smtp.example.com"
        cfg.smtp_user = "user@example.com"
        cfg.smtp_password = "password"
        self.assertTrue(cfg.is_email_upload_configured)

    def test_app_config_load_custom_openai_compatible(self):
        env_vars = {
            "STRAVA_CLIENT_ID": "strava123",
            "STRAVA_CLIENT_SECRET": "stravasecret",
            "STRAVA_REFRESH_TOKEN": "refresh123",
            "STRAVA_ATHLETE_ID": "99999",
            "AI_ENABLED": "true",
            "AI_BASE_URL": "http://localhost:11434/v1",
            "AI_MODEL": "llama3.2",
            "AI_LANGUAGE": "Spanish",
            "AI_TEMPERATURE": "0.7",
            "SYNC_INTERVAL": "1800",
            "SYNC_LIMIT": "25",
            "SYNC_AUTO_ANALYZE": "true",
            "SYNC_OUTPUT_DIR": "/tmp/custom_sync",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            app_cfg = AppConfig.load()

            self.assertEqual(app_cfg.strava.client_id, "strava123")
            self.assertEqual(app_cfg.strava.athlete_id, 99999)
            self.assertEqual(app_cfg.strava.refresh_token, "refresh123")

            self.assertTrue(app_cfg.ai.enabled)
            self.assertEqual(app_cfg.ai.base_url, "http://localhost:11434/v1")
            self.assertEqual(app_cfg.ai.model, "llama3.2")
            self.assertEqual(app_cfg.ai.language, "Spanish")
            self.assertEqual(app_cfg.ai.temperature, 0.7)

            self.assertEqual(app_cfg.sync.interval_seconds, 1800)
            self.assertEqual(app_cfg.sync.limit, 25)
            self.assertTrue(app_cfg.sync.auto_analyze)
            self.assertEqual(str(app_cfg.sync.output_dir), "/tmp/custom_sync")

    def test_sync_config_smtp_fallback_from_lago(self):
        env_vars = {
            "LAGO_IMAP_SERVER": "mailserver.maurodruwel.be",
            "LAGO_IMAP_USER": "sports@maurodruwel.be",
            "LAGO_IMAP_PASSWORD": "supersecretpassword",
            "TP_EMAIL": "athlete.upload@trainingpeaks.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            app_cfg = AppConfig.load()
            self.assertTrue(app_cfg.sync.is_email_upload_configured)
            self.assertEqual(app_cfg.sync.smtp_host, "mailserver.maurodruwel.be")
            self.assertEqual(app_cfg.sync.smtp_user, "sports@maurodruwel.be")
            self.assertEqual(app_cfg.sync.smtp_password, "supersecretpassword")
            self.assertEqual(app_cfg.sync.smtp_from, "sports@maurodruwel.be")
            self.assertEqual(app_cfg.sync.tp_email, "athlete.upload@trainingpeaks.com")

    def test_garmin_config_properties_and_load(self):
        from src.config import GarminConfig
        cfg = GarminConfig()
        self.assertFalse(cfg.is_configured)

        cfg.email = "mauro@example.com"
        cfg.password = "secret"
        self.assertTrue(cfg.is_configured)

        env_vars = {
            "GARMIN_EMAIL": "athlete@garmin.com",
            "GARMIN_PASSWORD": "garminpass123",
            "GARMIN_TOKEN_FILE": "/tmp/custom_tokens.json",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            app_cfg = AppConfig.load()
            self.assertTrue(app_cfg.garmin.is_configured)
            self.assertEqual(app_cfg.garmin.email, "athlete@garmin.com")
            self.assertEqual(app_cfg.garmin.password, "garminpass123")
            self.assertEqual(app_cfg.garmin.token_file, "/tmp/custom_tokens.json")
