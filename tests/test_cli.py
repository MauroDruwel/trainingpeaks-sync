"""
Unit tests for CLI argument parsing and command dispatching.
"""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.cli import create_parser, cmd_status, cmd_sync, cmd_auth, cmd_analyze, main
from src.config import AppConfig, StravaConfig, AIConfig, SyncConfig
from src.models import SyncBatchSummary


class TestCLI(unittest.TestCase):
    """Test CLI commands and argument parsing."""

    def test_create_parser_subcommands(self):
        parser = create_parser()

        # Test sync args
        args_sync = parser.parse_args(["sync", "--daemon", "--interval", "1800", "--dry-run"])
        self.assertEqual(args_sync.command, "sync")
        self.assertTrue(args_sync.daemon)
        self.assertEqual(args_sync.interval, 1800)
        self.assertTrue(args_sync.dry_run)

        # Test auth args
        args_auth = parser.parse_args(["auth", "--name", "Mauro", "--timeout", "90"])
        self.assertEqual(args_auth.command, "auth")
        self.assertEqual(args_auth.name, "Mauro")
        self.assertEqual(args_auth.timeout, 90)

        # Test status args
        args_status = parser.parse_args(["status"])
        self.assertEqual(args_status.command, "status")

        # Test analyze args
        args_analyze = parser.parse_args(["analyze", "sample.tcx", "--sport", "Bike", "--tts"])
        self.assertEqual(args_analyze.command, "analyze")
        self.assertEqual(args_analyze.tcx_file, "sample.tcx")
        self.assertEqual(args_analyze.sport, "Bike")
        self.assertTrue(args_analyze.tts)

    def test_cmd_status(self):
        config = AppConfig()
        with patch("builtins.print"):
            exit_code = cmd_status(config)
            self.assertEqual(exit_code, 0)

    def test_cmd_sync_success(self):
        config = AppConfig()
        parser = create_parser()
        args = parser.parse_args(["sync", "--once"])

        with patch("src.cli.SyncScheduler") as mock_sched_cls, \
             patch("builtins.print"):
            mock_sched = mock_sched_cls.return_value
            mock_sched.run_once.return_value = SyncBatchSummary(total_found=2, newly_synced=2, failed=0)

            exit_code = cmd_sync(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_sync_with_failures(self):
        config = AppConfig()
        parser = create_parser()
        args = parser.parse_args(["sync", "--once"])

        with patch("src.cli.SyncScheduler") as mock_sched_cls, \
             patch("builtins.print"):
            mock_sched = mock_sched_cls.return_value
            mock_sched.run_once.return_value = SyncBatchSummary(total_found=2, newly_synced=1, failed=1)

            exit_code = cmd_sync(args, config)
            self.assertEqual(exit_code, 1)

    def test_cmd_auth_not_configured(self):
        config = AppConfig(strava=StravaConfig())
        parser = create_parser()
        args = parser.parse_args(["auth"])

        with patch("builtins.print"):
            exit_code = cmd_auth(args, config)
            self.assertEqual(exit_code, 1)

    def test_cmd_auth_success(self):
        config = AppConfig(strava=StravaConfig(client_id="id", client_secret="sec"))
        parser = create_parser()
        args = parser.parse_args(["auth", "--name", "Mauro"])

        mock_token = MagicMock(athlete_name="Mauro", athlete_id=12345)
        with patch("src.cli.StravaOAuthClient") as mock_oauth_cls, \
             patch("builtins.print"):
            mock_oauth = mock_oauth_cls.return_value
            mock_oauth.authorize_athlete.return_value = mock_token

            exit_code = cmd_auth(args, config)
            self.assertEqual(exit_code, 0)

    def test_cmd_analyze_file_not_found(self):
        config = AppConfig()
        parser = create_parser()
        args = parser.parse_args(["analyze", "non_existent_file.tcx"])

        with patch("builtins.print"):
            exit_code = cmd_analyze(args, config)
            self.assertEqual(exit_code, 1)

    def test_main_default_to_sync(self):
        with patch("src.cli.cmd_sync", return_value=0) as mock_cmd_sync, \
             patch("src.cli.AppConfig.load"):
            exit_code = main([])
            self.assertEqual(exit_code, 0)
            mock_cmd_sync.assert_called_once()

    def test_cmd_lago(self):
        config = AppConfig()
        parser = create_parser()
        args = parser.parse_args(["lago"])
        with patch("src.cli.LagoIMAPClient.fetch_reservations", return_value=[]), \
             patch("builtins.print"):
            exit_code = main(["lago"])
            self.assertEqual(exit_code, 0)

    def test_cmd_studentapp(self):
        config = AppConfig()
        parser = create_parser()
        args = parser.parse_args(["studentapp"])
        with patch("src.cli.StudentAppClient.fetch_reservations", return_value=[]), \
             patch("builtins.print"):
            exit_code = main(["studentapp"])
            self.assertEqual(exit_code, 0)

    def test_cmd_nimstats(self):
        fake_info = MagicMock()
        fake_info.score = 65.0
        fake_info.intelligence = 40.0
        fake_info.uptime = 99.5
        fake_info.avg_response_time_ms = 12000.0
        fake_info.avg_throughput_tps = 45.0

        with patch("src.ai.nimstats.NIMStatsClient.get_best_model", return_value=("deepseek-ai/deepseek-v4.1-flash", fake_info)), \
             patch("builtins.print"):
            exit_code = main(["nimstats", "--strategy", "intelligence"])
            self.assertEqual(exit_code, 0)

    def test_cmd_sync_force(self):
        config = AppConfig()
        parser = create_parser()
        args = parser.parse_args(["sync", "--force"])
        self.assertTrue(args.force)

        with patch("src.cli.SyncScheduler") as mock_sched_cls, \
             patch("builtins.print"):
            mock_sched = mock_sched_cls.return_value
            mock_sched.run_once.return_value = SyncBatchSummary(total_found=1, newly_synced=1)
            exit_code = cmd_sync(args, config)
            self.assertEqual(exit_code, 0)
            mock_sched.run_once.assert_called_once_with(
                athlete_id=None,
                limit=None,
                dry_run=False,
                force_ai=None,
                force=True,
            )

    def test_cmd_test_email(self):
        with patch("src.cli.TrainingPeaksEmailUploader.test_connection", return_value=(True, "Success")), \
             patch("builtins.print"):
            exit_code = main(["test-email"])
            self.assertEqual(exit_code, 0)

    def test_cmd_garmin_auth(self):
        with patch("src.cli.GarminUploader.test_connection", return_value=(True, "Connected as Athlete")), \
             patch("src.cli.AppConfig.load") as mock_load, \
             patch("builtins.print"):
            mock_cfg = MagicMock()
            mock_cfg.garmin.is_configured = True
            mock_cfg.garmin.email = "mauro@example.com"
            mock_cfg.garmin.token_file = ".garmin_tokens.json"
            mock_load.return_value = mock_cfg

            exit_code = main(["garmin-auth"])
            self.assertEqual(exit_code, 0)

    def test_cmd_studentapp_test(self):
        with patch("src.cli.StudentAppClient.test_connection", return_value=(True, "Connected")), \
             patch("builtins.print"):
            exit_code = main(["studentapp", "--test"])
            self.assertEqual(exit_code, 0)

    def test_cmd_studentapp_login(self):
        with patch("src.cli.StudentAppClient.login", return_value=(True, "Success")), \
             patch("src.cli.AppConfig.load") as mock_load, \
             patch("builtins.print"):
            mock_cfg = MagicMock()
            mock_cfg.studentapp.email = "student@ugent.be"
            mock_cfg.studentapp.password = "secret"
            mock_cfg.studentapp.token_file = ".studentapp_tokens.json"
            mock_load.return_value = mock_cfg

            exit_code = main(["studentapp", "--login"])
            self.assertEqual(exit_code, 0)

    def test_cmd_studentapp_auth(self):
        with patch("src.cli.StudentAppClient.login", return_value=(True, "Success")), \
             patch("src.cli.AppConfig.load") as mock_load, \
             patch("builtins.print"):
            mock_cfg = MagicMock()
            mock_cfg.studentapp.email = "student@ugent.be"
            mock_cfg.studentapp.password = "secret"
            mock_cfg.studentapp.token_file = ".studentapp_tokens.json"
            mock_load.return_value = mock_cfg

            exit_code = main(["studentapp-auth"])
            self.assertEqual(exit_code, 0)
