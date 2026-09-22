"""
Command line interface for Strava to TrainingPeaks (Mauro Edition).
Provides automated cron/daemon sync, athlete authentication, status, and AI analysis.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Optional, List

from .config import AppConfig
from .models import Sport, AnalysisConfig
from .strava.oauth import StravaOAuthClient
from .sync.engine import SyncEngine
from .sync.scheduler import SyncScheduler
from .sync.state import SyncStateManager
from .ai.analyzer import AIAnalyzer
from .ai.tts import TTSGenerator
from .tcx.formatter import validate_tcx_file


BANNER = r"""
  ___ _                          _         _____ ___ 
 / __| |_ _ _ __ ___ __ __ _    | |_ ___  |_   _| _ \
 \__ \  _| '_/ _` \ V  V / _` |   |  _/ _ \   | | |  _/
 |___/\__|_| \__,_|\_/\_/\__,_|   \__\___/   |_| |_|  
               [ Mauro Edition • Automated Sync ]
"""


def create_parser() -> argparse.ArgumentParser:
    """Create top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="strava-to-trainingpeaks",
        description="Automated Strava to TrainingPeaks synchronization tool with AI analysis.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # --- Sync command (default) ---
    sync_parser = subparsers.add_parser("sync", help="Run automated sync (cron or daemon)")
    sync_parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Run once and exit (default, optimal for crontab)",
    )
    sync_parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously as a background daemon",
    )
    sync_parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Interval in seconds between sync runs when in daemon mode (default: 3600)",
    )
    sync_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of recent Strava activities to inspect (default: 10)",
    )
    sync_parser.add_argument(
        "--athlete-id",
        type=int,
        default=None,
        help="Specific athlete ID to sync (defaults to first authorized)",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check activities without downloading or saving files",
    )
    sync_parser.add_argument(
        "--ai",
        dest="ai",
        action="store_const",
        const=True,
        default=None,
        help="Force enable AI analysis on new activities",
    )
    sync_parser.add_argument(
        "--no-ai",
        dest="ai",
        action="store_const",
        const=False,
        help="Disable AI analysis on new activities",
    )
    sync_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save downloaded TCX files and analysis reports",
    )

    # --- Auth command ---
    auth_parser = subparsers.add_parser("auth", help="Authorize a Strava athlete via OAuth")
    auth_parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Name or alias for the athlete being authorized",
    )
    auth_parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds to wait for browser authorization (default: 120)",
    )

    # --- Status command ---
    subparsers.add_parser("status", help="Show system configuration, token health, and sync history")

    # --- Analyze command ---
    analyze_parser = subparsers.add_parser("analyze", help="Run AI analysis on an existing TCX file")
    analyze_parser.add_argument("tcx_file", type=str, help="Path to TCX file to analyze")
    analyze_parser.add_argument(
        "--sport",
        type=str,
        choices=["Bike", "Run", "Swim", "Other"],
        default="Run",
        help="Sport type (default: Run)",
    )
    analyze_parser.add_argument(
        "--plan",
        type=str,
        default="",
        help="Planned workout details or target metrics",
    )
    analyze_parser.add_argument(
        "--language",
        type=str,
        default=None,
        help="Language for analysis output (default: configured language or English)",
    )
    analyze_parser.add_argument(
        "--tts",
        action="store_true",
        help="Generate audio summary MP3 using speech synthesis",
    )

    # --- Interactive command ---
    subparsers.add_parser("interactive", help="Start the original step-by-step interactive CLI")

    # --- Coach command ---
    subparsers.add_parser("coach", help="Start multi-athlete coach mode")

    return parser


def cmd_sync(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute the sync command."""
    if args.output_dir:
        config.sync.output_dir = Path(args.output_dir)

    engine = SyncEngine(config=config)
    scheduler = SyncScheduler(engine=engine, config=config)

    if args.daemon:
        interval = args.interval or config.sync.interval_seconds
        scheduler.run_daemon(
            interval_seconds=interval,
            athlete_id=args.athlete_id,
            limit=args.limit,
            force_ai=args.ai,
        )
        return 0

    # One-shot cron mode
    print(f"🚀 Running Strava to TrainingPeaks Sync...")
    summary = scheduler.run_once(
        athlete_id=args.athlete_id,
        limit=args.limit,
        dry_run=args.dry_run,
        force_ai=args.ai,
    )

    print("\n" + "=" * 50)
    print(f"📊 Sync Summary:")
    print(f"  • Total activities examined: {summary.total_found}")
    print(f"  • Newly downloaded & formatted: {summary.newly_synced}")
    print(f"  • Already synced (skipped): {summary.already_synced}")
    if summary.failed > 0:
        print(f"  • Failed: {summary.failed}")
    print("=" * 50 + "\n")

    return 0 if summary.failed == 0 else 1


def cmd_auth(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute the athlete OAuth authorization flow."""
    if not config.strava.is_oauth_configured:
        print("❌ Strava OAuth is not configured.")
        print("Please set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in your .env or environment.")
        return 1

    oauth_client = StravaOAuthClient(config.strava.token_file)
    print(f"\n🔐 Starting Strava OAuth authorization (timeout: {args.timeout}s)...")
    token = oauth_client.authorize_athlete(athlete_name=args.name, timeout=args.timeout)

    if token:
        print(f"✅ Authorization successful for {token.athlete_name} (ID: {token.athlete_id})!")
        print(f"💾 Token securely stored in: {config.strava.token_file}")
        return 0
    else:
        print("❌ Authorization failed or timed out. Please try again.")
        return 1


def cmd_status(config: AppConfig) -> int:
    """Display system status, athlete token status, and sync history."""
    print("\n" + "=" * 55)
    print("📊 STRAVA TO TRAININGPEAKS STATUS")
    print("=" * 55)

    # Strava configuration
    print("\n[Strava Configuration]")
    if config.strava.is_oauth_configured:
        print(f"  • Client ID: {config.strava.client_id}")
        print("  • Client Secret: [Set]")
    else:
        print("  • OAuth Credentials: ❌ Not configured (set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET)")

    if config.strava.refresh_token:
        print("  • Headless Refresh Token: ✅ Present in environment")

    # Stored athletes
    oauth_client = None
    if config.strava.is_oauth_configured:
        try:
            oauth_client = StravaOAuthClient(config.strava.token_file)
            athletes = oauth_client.list_athletes()
            print(f"\n[Registered Athletes: {len(athletes)}]")
            if athletes:
                for ath_id, name in athletes.items():
                    tok = oauth_client.storage.get_token(ath_id)
                    health = "🟢 Valid" if tok and not tok.is_expired() else "🟡 Needs refresh"
                    print(f"  • {name} (ID: {ath_id}): {health}")
            else:
                print("  • None registered yet. Run 'strava-to-trainingpeaks auth' to add an athlete.")
        except Exception as err:
            print(f"  • Error loading athlete tokens: {err}")

    # AI Configuration
    print("\n[AI Analysis]")
    print(f"  • Enabled: {'✅ Yes' if config.ai.enabled else '⚪ No (enable with AI_ENABLED=true or provide key/url)'}")
    if config.ai.enabled:
        print(f"  • Endpoint: {config.ai.base_url or 'Default OpenAI API'}")
        print(f"  • Model: {config.ai.model}")
        print(f"  • Language: {config.ai.language}")
        print(f"  • TTS: {'Enabled' if config.ai.tts_enabled else 'Disabled'}")

    # Sync state
    state_mgr = SyncStateManager(config.sync.state_file)
    print("\n[Sync State]")
    print(f"  • Output directory: {config.sync.output_dir.resolve()}")
    print(f"  • State file: {config.sync.state_file.resolve()}")
    print(f"  • Last sync: {state_mgr.get_last_sync() or 'Never'}")
    print(f"  • Total synced activities: {state_mgr.get_total_synced_count()}")
    if config.sync.is_email_upload_configured:
        print(f"  • TrainingPeaks Email Upload: ✅ Configured -> {config.sync.tp_email}")
    else:
        print("  • TrainingPeaks Email Upload: ⚪ Not configured (manual file upload or set TP_EMAIL & SMTP_*)")

    print("\n" + "=" * 55 + "\n")
    return 0


def cmd_analyze(args: argparse.Namespace, config: AppConfig) -> int:
    """Run AI analysis on a local TCX file."""
    tcx_path = Path(args.tcx_file)
    if not tcx_path.is_file():
        print(f"❌ File not found: {tcx_path}")
        return 1

    valid, tcx_data = validate_tcx_file(str(tcx_path))
    if not valid or not tcx_data:
        print(f"❌ Invalid or empty TCX file: {tcx_path}")
        return 1

    sport = Sport(args.sport)
    analysis_config = AnalysisConfig(
        training_plan=args.plan,
        language=args.language or config.ai.language,
    )

    analyzer = AIAnalyzer(config.ai)
    print(f"🤖 Analyzing {tcx_path.name} ({sport.value}) using model '{config.ai.model}'...")

    try:
        report = analyzer.analyze(tcx_data, sport, analysis_config)
        print("\n" + "=" * 50)
        print("AI TRAINING REPORT")
        print("=" * 50)
        print(report)
        print("=" * 50 + "\n")

        if args.tts:
            print("🔊 Generating audio summary...")
            tts = TTSGenerator(config.ai)
            audio_path = tts.generate_audio_summary(report)
            if audio_path:
                print(f"✅ Audio summary saved to: {audio_path}")

        return 0
    except Exception as err:
        print(f"❌ Analysis failed: {err}")
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    if argv is None:
        argv = sys.argv[1:]

    parser = create_parser()

    # If no arguments provided, default to 'sync' or show help
    if not argv:
        argv = ["sync", "--once"]

    args = parser.parse_args(argv)
    config = AppConfig.load()

    if args.command == "sync":
        return cmd_sync(args, config)
    elif args.command == "auth":
        return cmd_auth(args, config)
    elif args.command == "status":
        return cmd_status(config)
    elif args.command == "analyze":
        return cmd_analyze(args, config)
    elif args.command == "interactive":
        from .main import TCXProcessor
        processor = TCXProcessor()
        processor.run()
        return 0
    elif args.command == "coach":
        from .coach_sync import coach_mode_main
        coach_mode_main()
        return 0
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
