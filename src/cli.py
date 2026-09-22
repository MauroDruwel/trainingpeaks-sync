"""
Command line interface for TrainingPeaks Multi-Source Sync (Mauro Edition).
Orchestrates Strava telemetry, LAGO email bookings, and StudentApp pool reservations.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Optional, List

from .config import AppConfig
from .models import Sport, AnalysisConfig
from .strava.oauth import StravaOAuthClient
from .sources.lago import LagoEmailParser, LagoIMAPClient
from .sources.studentapp import StudentAppParser, StudentAppClient
from .sync.engine import SyncEngine
from .sync.scheduler import SyncScheduler
from .sync.state import SyncStateManager
from .ai.analyzer import AIAnalyzer
from .ai.tts import TTSGenerator
from .tcx.formatter import validate_tcx_file


BANNER = r"""
  _____ _____    ______                  
 |_   _|  __ \  / ____/                  
   | | | |__) || (___  _   _ _ __   ___ 
   | | |  ___/  \___ \| | | | '_ \ / __|
  _| |_| |      ____) | |_| | | | | (__ 
 |_____|_|     |_____/ \__, |_| |_|\___|
                        __/ |           
                       |___/  [ Mauro Edition ]
 Multi-Source: Strava + LAGO Swim + StudentApp -> TrainingPeaks
"""


def create_parser() -> argparse.ArgumentParser:
    """Create top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="trainingpeaks-sync",
        description="Multi-source TrainingPeaks sync tool for Strava, LAGO swim reservations, and StudentApp bookings.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # --- Sync command (default) ---
    sync_parser = subparsers.add_parser("sync", help="Run automated sync across all sources")
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
        help="Max number of recent activities to inspect (default: 10)",
    )
    sync_parser.add_argument(
        "--athlete-id",
        type=int,
        default=None,
        help="Specific Strava athlete ID to sync (defaults to first authorized)",
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
        help="Force enable AI coaching analysis on new activities",
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

    # --- LAGO command ---
    lago_parser = subparsers.add_parser("lago", help="Check and inspect LAGO swimming reservation emails")
    lago_parser.add_argument(
        "--eml",
        type=str,
        default=None,
        help="Path to an .eml email file to parse directly",
    )

    # --- StudentApp command ---
    student_parser = subparsers.add_parser("studentapp", help="Check and inspect StudentApp pool bookings")
    student_parser.add_argument(
        "--har",
        type=str,
        default=None,
        help="Path to a .har HTTP archive export file to parse bookings from",
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
    """Execute the multi-source sync command."""
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
    print(BANNER)
    print(f"🚀 Running TrainingPeaks Multi-Source Sync...")
    summary = scheduler.run_once(
        athlete_id=args.athlete_id,
        limit=args.limit,
        dry_run=args.dry_run,
        force_ai=args.ai,
    )

    print("\n" + "=" * 55)
    print(f"📊 Sync Summary:")
    print(f"  • Total reconciled workouts: {summary.total_found}")
    print(f"  • Newly processed & saved: {summary.newly_synced}")
    print(f"  • Already synced (skipped): {summary.already_synced}")
    if summary.failed > 0:
        print(f"  • Failed: {summary.failed}")
    print("=" * 55 + "\n")

    return 0 if summary.failed == 0 else 1


def cmd_lago(args: argparse.Namespace, config: AppConfig) -> int:
    """Inspect or fetch LAGO reservation emails."""
    print("\n🏊 LAGO Swimming Reservation Inspector")
    print("-" * 50)

    if args.eml:
        eml_path = Path(args.eml)
        print(f"Reading EML file: {eml_path}")
        res = LagoEmailParser.parse_eml_file(eml_path)
        if res:
            _print_reservation(res)
            return 0
        else:
            print("❌ No valid LAGO reservation found in EML file.")
            return 1

    client = LagoIMAPClient(config.lago)
    reservations = client.fetch_reservations()
    if not reservations:
        print("No LAGO reservations found (or IMAP unconfigured).")
        print(f"Target email: {config.lago.target_email}, account: {config.lago.imap_user}")
        return 0

    print(f"Found {len(reservations)} LAGO reservation(s):\n")
    for r in reservations:
        _print_reservation(r)
    return 0


def cmd_studentapp(args: argparse.Namespace, config: AppConfig) -> int:
    """Inspect or parse StudentApp bookings."""
    print("\n🎓 StudentApp Pool Booking Inspector")
    print("-" * 50)

    har_path = Path(args.har) if args.har else config.studentapp.har_path
    if har_path:
        print(f"Reading HAR file: {har_path}")
        reservations = StudentAppParser.parse_har_file(har_path)
    else:
        client = StudentAppClient(config.studentapp)
        reservations = client.fetch_reservations()

    if not reservations:
        print("No StudentApp bookings found.")
        print("Tip: Provide a .har export file using --har <path> or configure STUDENTAPP_HAR_PATH in .env")
        return 0

    print(f"Found {len(reservations)} StudentApp booking(s):\n")
    for r in reservations:
        _print_reservation(r)
    return 0


def _print_reservation(r) -> None:
    """Format single reservation output."""
    print(f"  • [{r.source.upper()}] Ref: #{r.reservation_id}")
    print(f"    Facility: {r.facility}")
    print(f"    Start:    {r.start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    if r.end_time:
        print(f"    End:      {r.end_time.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"    Duration: {r.duration_seconds // 60} mins\n")


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
    """Display system status across all 3 sources, AI, and destinations."""
    print("\n" + "=" * 60)
    print("📊 TRAININGPEAKS MULTI-SOURCE SYNC STATUS")
    print("=" * 60)

    # 1. Strava Source
    print("\n[1. Strava Watch Telemetry]")
    if config.strava.is_oauth_configured:
        print(f"  • Client ID: {config.strava.client_id}")
        print("  • Credentials: ✅ Present")
    else:
        print("  • Credentials: ⚪ Not configured")

    if config.strava.refresh_token:
        print("  • Headless Refresh Token: ✅ Present in environment")

    if config.strava.is_oauth_configured:
        try:
            oauth_client = StravaOAuthClient(config.strava.token_file)
            athletes = oauth_client.list_athletes()
            print(f"  • Registered Athletes: {len(athletes)}")
            for ath_id, name in athletes.items():
                tok = oauth_client.storage.get_token(ath_id)
                health = "🟢 Valid" if tok and not tok.is_expired() else "🟡 Needs refresh"
                print(f"    - {name} (ID: {ath_id}): {health}")
        except Exception as err:
            print(f"  • Error reading tokens: {err}")

    # 2. LAGO Swimming Reservations
    print("\n[2. LAGO Swimming Reservations]")
    print(f"  • Target Email: {config.lago.target_email}")
    print(f"  • Mailbox Account: {config.lago.imap_user or 'None'}")
    if config.lago.is_configured:
        print(f"  • IMAP Server: ✅ Configured ({config.lago.imap_server}:{config.lago.imap_port})")
    else:
        print("  • IMAP Server: ⚪ Not configured (set LAGO_IMAP_SERVER and LAGO_IMAP_PASSWORD in .env)")

    # 3. StudentApp Bookings
    print("\n[3. StudentApp Bookings]")
    if config.studentapp.har_path:
        har_status = "✅ Found" if config.studentapp.har_path.exists() else "❌ File not found"
        print(f"  • HAR File: {config.studentapp.har_path} ({har_status})")
    else:
        print("  • HAR File: ⚪ None specified")

    if config.studentapp.api_url:
        print(f"  • Live API: {config.studentapp.api_url}")
    else:
        print("  • Live API: ⚪ Not configured")

    # 4. Reconciliation & Synthetic Workouts
    print("\n[4. Multi-Source Fusion & Watch-Forgotten Support]")
    print(f"  • Auto-generate synthetic workout if watch forgotten: {'✅ Yes' if config.fusion.auto_generate_synthetic_if_watch_forgotten else '⚪ No'}")
    print(f"  • Default synthetic swim distance: {config.fusion.synthetic_swim_distance_meters:.0f}m")
    print(f"  • Default duration: {config.fusion.synthetic_swim_duration_seconds // 60} mins")
    print(f"  • Matching time window: ±{config.fusion.time_window_minutes} mins")

    # 5. AI Configuration
    print("\n[5. AI Coaching Analysis (OpenAI-Compatible)]")
    print(f"  • Enabled: {'✅ Yes' if config.ai.enabled else '⚪ No'}")
    if config.ai.enabled:
        print(f"  • Endpoint: {config.ai.base_url or 'Default OpenAI API'}")
        print(f"  • Model: {config.ai.model}")
        print(f"  • Language: {config.ai.language}")
        print(f"  • Speech (TTS): {'Enabled' if config.ai.tts_enabled else 'Disabled'}")

    # 6. TrainingPeaks Destination
    state_mgr = SyncStateManager(config.sync.state_file)
    print("\n[6. TrainingPeaks Destination & Sync State]")
    print(f"  • Output Directory: {config.sync.output_dir.resolve()}")
    print(f"  • State File: {config.sync.state_file.resolve()}")
    print(f"  • Last Sync: {state_mgr.get_last_sync() or 'Never'}")
    print(f"  • Total Synced Activities: {state_mgr.get_total_synced_count()}")
    if config.sync.is_email_upload_configured:
        print(f"  • Email Direct Upload: ✅ Configured -> {config.sync.tp_email}")
    else:
        print("  • Email Direct Upload: ⚪ Not configured (manual file drop or set TP_EMAIL & SMTP_*)")

    print("\n" + "=" * 60 + "\n")
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

    # If no arguments provided, default to 'sync'
    if not argv:
        argv = ["sync", "--once"]

    args = parser.parse_args(argv)
    config = AppConfig.load()

    if args.command == "sync":
        return cmd_sync(args, config)
    elif args.command == "lago":
        return cmd_lago(args, config)
    elif args.command == "studentapp":
        return cmd_studentapp(args, config)
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
