"""
Command line interface for TrainingPeaks Multi-Source Sync (Mauro Edition).
Orchestrates Strava telemetry, LAGO email bookings, and StudentApp pool reservations.
"""
import argparse
import logging
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
from .sync.email import TrainingPeaksEmailUploader
from .garmin.client import GarminUploader
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
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-sync and re-upload of activities even if previously recorded in state",
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
    student_parser.add_argument(
        "--test",
        action="store_true",
        help="Test StudentApp connection and authentication",
    )
    student_parser.add_argument(
        "--login",
        action="store_true",
        help="Authenticate with email/password and refresh cached session",
    )

    # --- StudentApp Auth command ---
    subparsers.add_parser(
        "studentapp-auth",
        help="Authenticate with StudentApp using email/password and cache session tokens",
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

    # --- Test-Email command ---
    subparsers.add_parser("test-email", help="Verify SMTP connection and TrainingPeaks email upload configuration")

    # --- Garmin Auth command ---
    subparsers.add_parser(
        "garmin-auth",
        help="Authenticate with Garmin Connect and cache session tokens for automatic TrainingPeaks sync",
    )

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

    # --- NIMStats command ---
    nim_parser = subparsers.add_parser("nimstats", help="Inspect top LLMs from Mauro's NIMStats (nimstats.maurodruwel.be)")
    nim_parser.add_argument(
        "--strategy",
        type=str,
        choices=["all", "intelligence", "balanced", "speed"],
        default="all",
        help="Strategy to inspect (default: all)",
    )
    nim_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force fresh lookup bypassing local cache",
    )
    nim_parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Override NIMStats API base URL",
    )

    return parser


def cmd_sync(args: argparse.Namespace, config: AppConfig) -> int:
    """Execute the multi-source sync command."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
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
        force=getattr(args, "force", False),
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

    client = StudentAppClient(config.studentapp)

    if getattr(args, "login", False):
        return cmd_studentapp_auth(args, config)

    if getattr(args, "test", False):
        print("Testing StudentApp connection & authentication...")
        ok, msg = client.test_connection()
        if ok:
            print(f"✅ {msg}")
            return 0
        else:
            print(f"❌ {msg}")
            return 1

    har_path = Path(args.har) if args.har else config.studentapp.har_path
    if har_path:
        print(f"Reading HAR file: {har_path}")
        reservations = StudentAppParser.parse_har_file(har_path)
    else:
        reservations = client.fetch_reservations()

    if not reservations:
        print("No StudentApp bookings found.")
        print("Tips:")
        print("  • Configure STUDENTAPP_EMAIL and STUDENTAPP_PASSWORD in .env")
        print("  • Run 'tp-sync studentapp --test' to verify connection")
        print("  • Run 'tp-sync studentapp --login' to authenticate and cache session")
        print("  • Or provide a .har export file using --har <path>")
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
    if config.lago.enabled and config.lago.is_configured:
        print(f"  • IMAP Server: ✅ Configured & Active ({config.lago.imap_server}:{config.lago.imap_port})")
    elif config.lago.is_configured:
        print(f"  • IMAP Server: ⚪ Disabled (LAGO_ENABLED=false)")
    else:
        print("  • IMAP Server: ⚪ Not configured (set LAGO_IMAP_SERVER and LAGO_IMAP_PASSWORD in .env)")

    # 3. StudentApp Bookings
    print("\n[3. StudentApp Bookings]")
    if config.studentapp.enabled and config.studentapp.is_configured:
        status_str = "✅ Active"
    elif config.studentapp.is_configured:
        status_str = "⚪ Disabled (STUDENTAPP_ENABLED=false)"
    else:
        status_str = "⚪ Disabled"
    print(f"  • Status: {status_str}")
    if config.studentapp.email:
        pw_indicator = "••••••••" if config.studentapp.password else "⚪ Missing"
        print(f"  • Account: {config.studentapp.email} (Password: {pw_indicator})")
    else:
        print("  • Account: ⚪ Not configured (set STUDENTAPP_EMAIL & STUDENTAPP_PASSWORD in .env)")

    token_path = Path(config.studentapp.token_file)
    if token_path.is_file():
        print(f"  • Session Cache: 🟢 Cached ({config.studentapp.token_file})")
    elif config.studentapp.email and config.studentapp.password:
        print("  • Session Cache: 🟡 Ready to authenticate on next sync")
    else:
        print("  • Session Cache: ⚪ None")

    if config.studentapp.api_url:
        print(f"  • API Endpoint: {config.studentapp.api_url}")
    if config.studentapp.har_path:
        har_status = "✅ Found" if config.studentapp.har_path.exists() else "❌ File not found"
        print(f"  • HAR File (Fallback): {config.studentapp.har_path} ({har_status})")

    # 4. Reconciliation & Synthetic Workouts
    print("\n[4. Multi-Source Fusion & Watch-Forgotten Support]")
    print(f"  • Auto-generate synthetic workout if watch forgotten: {'✅ Yes' if config.fusion.auto_generate_synthetic_if_watch_forgotten else '⚪ No'}")
    print(f"  • Default synthetic swim distance: {config.fusion.synthetic_swim_distance_meters:.0f}m")
    print(f"  • Default duration: {config.fusion.synthetic_swim_duration_seconds // 60} mins")
    print(f"  • Matching time window: ±{config.fusion.time_window_minutes} mins")

    # 5. AI Coaching Analysis (OpenAI-Compatible)
    is_nim = config.ai.is_nvidia_nim
    provider_name = "NVIDIA NIM" if is_nim else (config.ai.provider or "OpenAI-Compatible")
    print(f"\n[5. AI Coaching Analysis ({provider_name})]")
    print(f"  • Enabled: {'✅ Yes' if config.ai.enabled else '⚪ No'}")
    if config.ai.enabled:
        print(f"  • Endpoint: {config.ai.effective_base_url or 'Default OpenAI API'}")
        if is_nim:
            print(f"  • NVIDIA NIM API Key: {'✅ Configured' if config.ai.effective_api_key else '⚪ Not configured'}")
        if config.ai.nimstats_enabled:
            print(f"  • NIMStats Dynamic Selection: ✅ Active ({config.ai.nimstats_url})")
            print(f"  • Strategy: {config.ai.nimstats_strategy}")
            try:
                from .ai.nimstats import get_nimstats_client
                client = get_nimstats_client(base_url=config.ai.nimstats_url)
                best_m, info = client.get_best_model(strategy=config.ai.nimstats_strategy, timeout=3.0)
                if info:
                    intel_str = f", Intel: {info.intelligence}" if info.intelligence is not None else ""
                    print(f"  • Top Resolved Model: {best_m} (Score: {info.score:.0f}{intel_str}, Uptime: {info.uptime:.1f}%)")
                else:
                    print(f"  • Top Resolved Model: {best_m} (Fallback)")
            except Exception as err:
                print(f"  • Top Resolved Model: ⚪ {err}")
        else:
            print(f"  • Model: {config.ai.model}")
        print(f"  • Language: {config.ai.language}")
        print(f"  • Speech (TTS): {'Enabled' if config.ai.tts_enabled else 'Disabled'}")

    # 6. TrainingPeaks Destination & Garmin Bridge
    state_mgr = SyncStateManager(config.sync.state_file)
    print("\n[6. TrainingPeaks Destination & Garmin Bridge]")
    print(f"  • Output Directory: {config.sync.output_dir.resolve()} (Manual calendar drop)")
    print(f"  • State File: {config.sync.state_file.resolve()}")
    print(f"  • Last Sync: {state_mgr.get_last_sync() or 'Never'}")
    print(f"  • Total Synced Activities: {state_mgr.get_total_synced_count()}")
    if config.garmin.enabled and config.garmin.is_configured:
        token_path = Path(config.garmin.token_file)
        token_status = "Tokens cached" if token_path.exists() else "Credentials configured"
        print(f"  • Garmin Connect Bridge: ✅ Active ({config.garmin.email or 'Cached session'}, {token_status})")
    elif config.garmin.is_configured:
        print("  • Garmin Connect Bridge: ⚪ Disabled (GARMIN_ENABLED=false)")
    else:
        print("  • Garmin Connect Bridge: ⚪ Not configured (set GARMIN_EMAIL & GARMIN_PASSWORD in .env)")

    print("\n" + "=" * 60 + "\n")
    return 0


def cmd_garmin_auth(args: argparse.Namespace, config: AppConfig) -> int:
    """Authenticate with Garmin Connect, handling MFA interactively if needed."""
    print("\n⌚ Garmin Connect Bridge Authentication")
    print("-" * 55)
    print("Garmin Connect automatically syncs uploaded activities directly")
    print("to your TrainingPeaks calendar via their official partner sync.")
    print("-" * 55)

    if not config.garmin.is_configured:
        print("❌ GARMIN_EMAIL and GARMIN_PASSWORD are not set in your .env file.")
        print("Please add to your .env file:")
        print("  GARMIN_EMAIL=your_garmin_login@email.com")
        print("  GARMIN_PASSWORD=your_garmin_password")
        return 1

    print(f"Authenticating as: {config.garmin.email or 'configured credentials'}...")
    uploader = GarminUploader(config.garmin)
    success, msg = uploader.test_connection(interactive=True)
    if success:
        print(f"\n✅ {msg}")
        print(f"💾 Session tokens saved to: {config.garmin.token_file}")
        print("🎉 Garmin Connect bridge is active! Any new synced workouts will automatically")
        print("   push to Garmin Connect and appear on your TrainingPeaks calendar!\n")
        return 0
    else:
        print(f"\n❌ {msg}\n")
        return 1


def cmd_studentapp_auth(args: argparse.Namespace, config: AppConfig) -> int:
    """Authenticate with StudentApp using email and password, caching session tokens."""
    print("\n🎓 StudentApp Authentication")
    print("-" * 55)

    if not (config.studentapp.email and config.studentapp.password):
        print("❌ STUDENTAPP_EMAIL and STUDENTAPP_PASSWORD are not set in your .env file.")
        print("Please add to your .env file:")
        print("  STUDENTAPP_EMAIL=your_student_email@example.com")
        print("  STUDENTAPP_PASSWORD=your_studentapp_password")
        return 1

    client = StudentAppClient(config.studentapp)
    endpoint = client.get_login_endpoint()
    if not endpoint:
        print("❌ Cannot determine StudentApp login endpoint.")
        print("Please set STUDENTAPP_LOGIN_URL or STUDENTAPP_API_URL in .env.")
        return 1

    print(f"Authenticating as: {config.studentapp.email}...")
    success, msg = client.login()
    if success:
        print(f"\n✅ {msg}")
        print(f"💾 Session tokens saved to: {config.studentapp.token_file}\n")
        return 0
    else:
        print(f"\n❌ {msg}\n")
        return 1


def cmd_test_email(args: argparse.Namespace, config: AppConfig) -> int:
    """Test SMTP connection and TrainingPeaks email upload readiness."""
    print("\n📧 TrainingPeaks Email Upload Diagnostic")
    print("-" * 55)
    print(f"  • TrainingPeaks Upload Email : {config.sync.tp_email or '❌ Not set (TP_EMAIL)'}")
    print(f"  • SMTP Host                  : {config.sync.smtp_host or '❌ Not set (SMTP_HOST)'}")
    print(f"  • SMTP Port                  : {config.sync.smtp_port}")
    print(f"  • SMTP Username              : {config.sync.smtp_user or '❌ Not set (SMTP_USER)'}")
    print(f"  • SMTP From Address          : {config.sync.smtp_from or '❌ Not set (SMTP_FROM)'}")
    print("-" * 55)

    uploader = TrainingPeaksEmailUploader(config.sync)
    success, msg = uploader.test_connection()
    if success:
        print(f"✅ {msg}")
        print("🎉 Ready to automatically email TCX workout files directly into TrainingPeaks!\n")
        return 0
    else:
        print(f"❌ {msg}\n")
        return 1


def cmd_nimstats(args: argparse.Namespace, config: AppConfig) -> int:
    """Query and display live model leaderboards from Mauro's NIMStats."""
    from .ai.nimstats import get_nimstats_client
    print("\n📊 NIMStats Model Leaderboard (https://nimstats.maurodruwel.be)")
    print("-" * 65)

    client = get_nimstats_client(base_url=args.url or config.ai.nimstats_url)
    strategies = ["intelligence", "balanced", "speed"] if args.strategy == "all" else [args.strategy]

    icons = {
        "intelligence": "🧠",
        "balanced": "⚖️",
        "speed": "⚡",
    }

    for strat in strategies:
        icon = icons.get(strat, "🤖")
        model, info = client.get_best_model(strategy=strat, timeout=5.0, force_refresh=args.refresh)
        if info:
            print(f"{icon} {strat.capitalize():<13}: {model}")
            metrics = [f"Score: {info.score:.0f}"]
            if info.intelligence is not None:
                metrics.append(f"Intel: {info.intelligence}")
            if info.uptime is not None:
                metrics.append(f"Uptime: {info.uptime:.1f}%")
            if info.avg_response_time_ms is not None:
                metrics.append(f"Latency: {info.avg_response_time_ms:.0f}ms")
            if info.avg_throughput_tps is not None:
                metrics.append(f"TPS: {info.avg_throughput_tps:.1f}")
            print(f"   └─ {', '.join(metrics)}")
        else:
            print(f"{icon} {strat.capitalize():<13}: {model} (Fallback)")

    print("-" * 65 + "\n")
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
    model_name, nim_info = analyzer.resolve_model()
    if nim_info:
        print(f"🤖 Analyzing {tcx_path.name} ({sport.value}) using top NIMStats model '{model_name}' (Intel: {nim_info.intelligence})...")
    else:
        print(f"🤖 Analyzing {tcx_path.name} ({sport.value}) using model '{model_name}'...")

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
    elif args.command == "studentapp-auth":
        return cmd_studentapp_auth(args, config)
    elif args.command == "auth":
        return cmd_auth(args, config)
    elif args.command == "status":
        return cmd_status(config)
    elif args.command == "garmin-auth":
        return cmd_garmin_auth(args, config)
    elif args.command == "test-email":
        return cmd_test_email(args, config)
    elif args.command == "nimstats":
        return cmd_nimstats(args, config)
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
