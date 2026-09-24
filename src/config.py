"""
Configuration loader and settings for TrainingPeaks Multi-Source Sync (Mauro Edition).
Supports Strava, LAGO email reservations, StudentApp bookings, and custom OpenAI endpoints.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .models import (
    DEFAULT_REDIRECT_URI,
    DEFAULT_SCOPES,
    DEFAULT_TOKEN_FILE,
    ProcessingConfig,
)


@dataclass
class StravaConfig:
    """Strava API and OAuth configuration."""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None
    access_token: Optional[str] = None
    athlete_id: Optional[int] = None
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: str = DEFAULT_SCOPES
    token_file: str = DEFAULT_TOKEN_FILE

    @property
    def is_oauth_configured(self) -> bool:
        """Check if OAuth client credentials are available."""
        return bool(self.client_id and self.client_secret)

    @property
    def is_headless_configured(self) -> bool:
        """Check if headless authentication (refresh token) is configured."""
        return bool(self.is_oauth_configured and self.refresh_token)


@dataclass
class LagoConfig:
    """Configuration for LAGO swimming reservation email retrieval via IMAP."""
    enabled: bool = False
    imap_server: Optional[str] = None
    imap_port: int = 993
    imap_user: Optional[str] = "sports@maurodruwel.be"
    imap_password: Optional[str] = None
    target_email: str = "swimming@maurodruwel.be"
    mailbox: str = "INBOX"
    sample_dir: Optional[Path] = None  # Local directory containing .eml files for offline/testing use

    @property
    def is_configured(self) -> bool:
        """Check if IMAP credentials or local sample directory are available."""
        return bool(
            (self.imap_server and self.imap_user and self.imap_password)
            or (self.sample_dir and self.sample_dir.exists())
        )


@dataclass
class StudentAppConfig:
    """Configuration for StudentApp pool reservation checking."""
    enabled: bool = False
    email: Optional[str] = None
    password: Optional[str] = None
    login_url: Optional[str] = None
    token_file: str = ".studentapp_tokens.json"
    har_path: Optional[Path] = None
    api_url: Optional[str] = None
    api_token: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        """Check if email/password, tokens, HAR file, or API credentials are provided."""
        return bool(
            (self.email and self.password)
            or (self.har_path and self.har_path.exists())
            or (self.api_url and self.api_token)
            or Path(self.token_file).exists()
        )


@dataclass
class GarminConfig:
    """Garmin Connect configuration for automatic TrainingPeaks bridging."""
    enabled: bool = False
    email: Optional[str] = None
    password: Optional[str] = None
    token_file: str = ".garmin_tokens.json"

    @property
    def is_configured(self) -> bool:
        """Check if Garmin Connect credentials or saved tokens exist."""
        return bool((self.email and self.password) or Path(self.token_file).exists())


@dataclass
class TrainingPdfConfig:
    """Optional PDF training plans input source."""
    enabled: bool = False
    directory: Path = Path("trainings")
    file_path: Optional[Path] = None

    @property
    def is_configured(self) -> bool:
        """Check if PDF directory or specific file exists."""
        return bool(
            (self.file_path and self.file_path.exists())
            or (self.directory and self.directory.exists())
        )


@dataclass
class FusionConfig:
    """Settings for multi-source workout reconciliation & synthetic activity generation."""
    time_window_minutes: int = 90
    synthetic_swim_distance_meters: float = 4500.0
    synthetic_swim_duration_seconds: int = 6300  # 1h 45m (105 mins)
    auto_generate_synthetic_if_watch_forgotten: bool = True


@dataclass
class AIConfig:
    """OpenAI-compatible AI configuration (supports NVIDIA NIM, Ollama, vLLM, OpenRouter, Groq, DeepSeek, etc.)."""
    enabled: bool = False
    provider: Optional[str] = None  # "nvidia", "ollama", "openai", "openrouter", etc.
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    model: str = "auto"
    language: str = "English"
    temperature: float = 0.3
    tts_enabled: bool = False
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"

    # NIMStats dynamic model selection (from https://nimstats.maurodruwel.be/)
    nimstats_enabled: bool = True
    nimstats_strategy: str = "intelligence"  # "intelligence", "balanced", "speed"
    nimstats_url: str = "https://nimstats.maurodruwel.be"

    @property
    def is_nvidia_nim(self) -> bool:
        """Check if target endpoint is NVIDIA NIM API."""
        base = self.effective_base_url or ""
        return (
            "api.nvidia.com" in base
            or self.provider == "nvidia"
            or bool(self.nvidia_api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY"))
        )

    @property
    def effective_base_url(self) -> Optional[str]:
        """Return the effective base URL."""
        if self.base_url:
            return self.base_url
        if self.provider == "nvidia" or self.nvidia_api_key or os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY"):
            return "https://integrate.api.nvidia.com/v1"
        return None

    @property
    def effective_api_key(self) -> str:
        """Return effective API key, defaulting to dummy for local endpoints if needed."""
        if self.api_key:
            return self.api_key
        if self.nvidia_api_key:
            return self.nvidia_api_key
        env_nvidia = os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
        if env_nvidia:
            return env_nvidia
        env_ai = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if env_ai:
            return env_ai
        base = self.effective_base_url
        if base and ("localhost" in base or "127.0.0.1" in base):
            return "dummy-local-key"
        return ""


@dataclass
class SyncConfig:
    """Configuration for automated sync runs and cron mode."""
    output_dir: Path = field(default_factory=lambda: Path("./synced_activities"))
    state_file: Path = field(default_factory=lambda: Path(".sync_state.json"))
    interval_seconds: int = 3600  # Default: 1 hour
    limit: int = 10
    auto_analyze: bool = False
    save_analysis_file: bool = True
    sport_filter: Optional[str] = None  # None means all sports

    # Optional TrainingPeaks email direct upload
    tp_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None

    @property
    def is_email_upload_configured(self) -> bool:
        """Check if automatic email upload to TrainingPeaks is configured."""
        return bool(self.tp_email and self.smtp_host and self.smtp_user and self.smtp_password)


@dataclass
class AppConfig:
    """Root application configuration."""
    strava: StravaConfig = field(default_factory=StravaConfig)
    lago: LagoConfig = field(default_factory=LagoConfig)
    studentapp: StudentAppConfig = field(default_factory=StudentAppConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    garmin: GarminConfig = field(default_factory=GarminConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    training_pdf: TrainingPdfConfig = field(default_factory=TrainingPdfConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)

    @classmethod
    def load(cls, env_path: Optional[str] = None) -> "AppConfig":
        """Load configuration from environment and optional .env file."""
        load_dotenv(dotenv_path=env_path)

        # 1. Strava
        strava_athlete_id_raw = os.getenv("STRAVA_ATHLETE_ID")
        athlete_id = int(strava_athlete_id_raw) if strava_athlete_id_raw and strava_athlete_id_raw.isdigit() else None

        strava = StravaConfig(
            client_id=os.getenv("STRAVA_CLIENT_ID"),
            client_secret=os.getenv("STRAVA_CLIENT_SECRET"),
            refresh_token=os.getenv("STRAVA_REFRESH_TOKEN"),
            access_token=os.getenv("STRAVA_ACCESS_TOKEN"),
            athlete_id=athlete_id,
            redirect_uri=os.getenv("STRAVA_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            scopes=os.getenv("STRAVA_SCOPES", DEFAULT_SCOPES),
            token_file=os.getenv("STRAVA_TOKEN_FILE", DEFAULT_TOKEN_FILE),
        )

        # 2. LAGO Email / IMAP
        lago_port_raw = os.getenv("LAGO_IMAP_PORT", "993")
        try:
            lago_port = int(lago_port_raw)
        except ValueError:
            lago_port = 993

        lago_sample_dir_str = os.getenv("LAGO_SAMPLE_DIR")
        lago_sample_dir = Path(lago_sample_dir_str) if lago_sample_dir_str else None

        lago_enabled_env = os.getenv("LAGO_ENABLED")
        lago_server = os.getenv("LAGO_IMAP_SERVER")
        lago_user = os.getenv("LAGO_IMAP_USER", "sports@maurodruwel.be")
        lago_pass = os.getenv("LAGO_IMAP_PASSWORD")
        lago_target = os.getenv("LAGO_TARGET_EMAIL", "swimming@maurodruwel.be")
        lago_mailbox = os.getenv("LAGO_MAILBOX", "INBOX")

        lago_enabled = (
            lago_enabled_env.lower() in ("true", "1", "yes")
            if lago_enabled_env is not None
            else bool(lago_server and lago_pass or (lago_sample_dir and lago_sample_dir.exists()))
        )

        lago = LagoConfig(
            enabled=lago_enabled,
            imap_server=lago_server,
            imap_port=lago_port,
            imap_user=lago_user,
            imap_password=lago_pass,
            target_email=lago_target,
            mailbox=lago_mailbox,
            sample_dir=lago_sample_dir,
        )

        # 3. StudentApp
        student_email = os.getenv("STUDENTAPP_EMAIL")
        student_password = os.getenv("STUDENTAPP_PASSWORD")
        student_login_url = os.getenv("STUDENTAPP_LOGIN_URL")
        student_token_file = os.getenv("STUDENTAPP_TOKEN_FILE", ".studentapp_tokens.json")
        har_path_str = os.getenv("STUDENTAPP_HAR_PATH")
        har_path = Path(har_path_str) if har_path_str else None
        student_url = os.getenv("STUDENTAPP_API_URL")
        student_token = os.getenv("STUDENTAPP_TOKEN")

        student_enabled_env = os.getenv("STUDENTAPP_ENABLED")
        student_enabled = (
            student_enabled_env.lower() in ("true", "1", "yes")
            if student_enabled_env is not None
            else bool(
                (student_email and student_password)
                or har_path
                or (student_url and student_token)
                or Path(student_token_file).exists()
            )
        )

        studentapp = StudentAppConfig(
            enabled=student_enabled,
            email=student_email,
            password=student_password,
            login_url=student_login_url,
            token_file=student_token_file,
            har_path=har_path,
            api_url=student_url,
            api_token=student_token,
        )

        # 4. Fusion
        fusion_window_raw = os.getenv("FUSION_TIME_WINDOW_MINUTES", "90")
        try:
            fusion_window = int(fusion_window_raw)
        except ValueError:
            fusion_window = 90

        fusion_dist_raw = os.getenv("SWIM_DEFAULT_DISTANCE_METERS", "4500.0")
        try:
            fusion_dist = float(fusion_dist_raw)
        except ValueError:
            fusion_dist = 4500.0

        fusion_dur_raw = os.getenv("SWIM_DEFAULT_DURATION_MINUTES", "105")
        try:
            fusion_dur = int(fusion_dur_raw) * 60
        except ValueError:
            fusion_dur = 6300

        synthetic_enabled = os.getenv("FUSION_AUTO_SYNTHETIC", "true").lower() in ("true", "1", "yes")

        fusion = FusionConfig(
            time_window_minutes=fusion_window,
            synthetic_swim_distance_meters=fusion_dist,
            synthetic_swim_duration_seconds=fusion_dur,
            auto_generate_synthetic_if_watch_forgotten=synthetic_enabled,
        )

        # 5. AI (NVIDIA NIM, Ollama, OpenRouter, Groq, DeepSeek, or standard OpenAI)
        nvidia_key = os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
        ai_provider = os.getenv("AI_PROVIDER")
        if not ai_provider and nvidia_key:
            ai_provider = "nvidia"

        ai_base_url = (
            os.getenv("AI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("OPENAI_API_BASE")
            or ("https://integrate.api.nvidia.com/v1" if ai_provider == "nvidia" or nvidia_key else None)
        )
        ai_api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or nvidia_key

        nimstats_enabled_env = os.getenv("NIMSTATS_ENABLED")
        nimstats_enabled = (
            nimstats_enabled_env.lower() in ("true", "1", "yes")
            if nimstats_enabled_env is not None
            else True
        )
        nimstats_strategy = os.getenv("NIMSTATS_STRATEGY", "intelligence")
        nimstats_url = os.getenv("NIMSTATS_URL", "https://nimstats.maurodruwel.be")

        ai_model_env = os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL")
        if not ai_model_env:
            if ai_provider == "nvidia" or nvidia_key or (ai_base_url and "api.nvidia.com" in ai_base_url):
                ai_model = "auto"
            elif ai_base_url and "localhost" in ai_base_url:
                ai_model = "llama3.2"
            else:
                ai_model = "auto" if nimstats_enabled else "gpt-4o-mini"
        else:
            ai_model = ai_model_env

        ai_enabled_env = os.getenv("AI_ENABLED")
        ai_enabled = (
            ai_enabled_env.lower() in ("true", "1", "yes")
            if ai_enabled_env is not None
            else bool(ai_api_key or ai_base_url or nvidia_key)
        )

        ai_lang = os.getenv("AI_LANGUAGE", "English")
        ai_temp_raw = os.getenv("AI_TEMPERATURE", "0.3")
        try:
            ai_temp = float(ai_temp_raw)
        except ValueError:
            ai_temp = 0.3

        tts_enabled = os.getenv("AI_TTS_ENABLED", "false").lower() in ("true", "1", "yes")

        ai = AIConfig(
            enabled=ai_enabled,
            provider=ai_provider,
            base_url=ai_base_url,
            api_key=ai_api_key,
            nvidia_api_key=nvidia_key,
            model=ai_model,
            language=ai_lang,
            temperature=ai_temp,
            tts_enabled=tts_enabled,
            tts_model=os.getenv("AI_TTS_MODEL", "gpt-4o-mini-tts"),
            tts_voice=os.getenv("AI_TTS_VOICE", "alloy"),
            nimstats_enabled=nimstats_enabled,
            nimstats_strategy=nimstats_strategy,
            nimstats_url=nimstats_url,
        )

        # 6. Sync / Cron
        output_dir_str = os.getenv("SYNC_OUTPUT_DIR") or "./synced_activities"
        state_file_str = os.getenv("SYNC_STATE_FILE") or ".sync_state.json"
        interval_raw = os.getenv("SYNC_INTERVAL", "3600")
        try:
            interval_sec = int(interval_raw)
        except ValueError:
            interval_sec = 3600

        limit_raw = os.getenv("SYNC_LIMIT", "10")
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 10

        auto_analyze = os.getenv("SYNC_AUTO_ANALYZE", "false").lower() in ("true", "1", "yes")
        save_analysis = os.getenv("SYNC_SAVE_ANALYSIS", "true").lower() in ("true", "1", "yes")
        smtp_port_raw = os.getenv("SMTP_PORT", "587")
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            smtp_port = 587

        # SMTP settings with smart fallback to LAGO mail server if available
        smtp_host = os.getenv("SMTP_HOST") or lago_server
        smtp_user = os.getenv("SMTP_USER") or lago_user
        smtp_password = os.getenv("SMTP_PASSWORD") or lago_pass
        smtp_from = os.getenv("SMTP_FROM") or smtp_user

        sync = SyncConfig(
            output_dir=Path(output_dir_str),
            state_file=Path(state_file_str),
            interval_seconds=interval_sec,
            limit=limit,
            auto_analyze=auto_analyze,
            save_analysis_file=save_analysis,
            sport_filter=os.getenv("SYNC_SPORT_FILTER"),
            tp_email=os.getenv("TP_EMAIL") or os.getenv("TRAININGPEAKS_EMAIL"),
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
        )

        # 7. Garmin Connect Bridge
        garmin_email = os.getenv("GARMIN_EMAIL")
        garmin_password = os.getenv("GARMIN_PASSWORD")
        garmin_token_file = os.getenv("GARMIN_TOKEN_FILE", ".garmin_tokens.json")
        garmin_enabled_env = os.getenv("GARMIN_ENABLED")
        garmin_enabled = (
            garmin_enabled_env.lower() in ("true", "1", "yes")
            if garmin_enabled_env is not None
            else bool(garmin_email or Path(garmin_token_file).exists())
        )

        garmin = GarminConfig(
            enabled=garmin_enabled,
            email=garmin_email,
            password=garmin_password,
            token_file=garmin_token_file,
        )

        # 8. Optional PDF Training Plans
        pdf_enabled_env = os.getenv("TRAINING_PDF_ENABLED")
        pdf_dir_env = os.getenv("TRAINING_PDF_DIR", "trainings")
        pdf_path_env = os.getenv("TRAINING_PDF_PATH")
        pdf_dir = Path(pdf_dir_env)
        pdf_path = Path(pdf_path_env) if pdf_path_env else None
        pdf_enabled = (
            pdf_enabled_env.lower() in ("true", "1", "yes")
            if pdf_enabled_env is not None
            else bool(pdf_path and pdf_path.exists())
        )

        training_pdf = TrainingPdfConfig(
            enabled=pdf_enabled,
            directory=pdf_dir,
            file_path=pdf_path,
        )

        return cls(
            strava=strava,
            lago=lago,
            studentapp=studentapp,
            fusion=fusion,
            ai=ai,
            garmin=garmin,
            sync=sync,
            training_pdf=training_pdf,
            processing=ProcessingConfig(),
        )
