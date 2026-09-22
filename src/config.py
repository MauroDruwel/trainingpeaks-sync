"""
Configuration loader and settings for Strava to TrainingPeaks.
Supports environment variables, .env file, and custom OpenAI-compatible endpoints.
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
class AIConfig:
    """OpenAI-compatible AI configuration (supports Ollama, vLLM, OpenRouter, Groq, etc.)."""
    enabled: bool = False
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str = "gpt-4o-mini"
    language: str = "English"
    temperature: float = 0.3
    tts_enabled: bool = False
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"

    @property
    def effective_api_key(self) -> str:
        """Return effective API key, defaulting to dummy for local endpoints if needed."""
        if self.api_key:
            return self.api_key
        # For local endpoints like Ollama or LM Studio, API key isn't strictly required
        if self.base_url and ("localhost" in self.base_url or "127.0.0.1" in self.base_url):
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
    ai: AIConfig = field(default_factory=AIConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)

    @classmethod
    def load(cls, env_path: Optional[str] = None) -> "AppConfig":
        """Load configuration from environment and optional .env file."""
        load_dotenv(dotenv_path=env_path)

        # Strava
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

        # AI (OpenAI or custom compatible endpoint like Ollama, OpenRouter, Groq, vLLM)
        ai_base_url = os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
        ai_api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
        ai_model = os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL") or ("llama3.2" if ai_base_url and "localhost" in ai_base_url else "gpt-4o-mini")
        ai_enabled_env = os.getenv("AI_ENABLED")
        ai_enabled = (
            ai_enabled_env.lower() in ("true", "1", "yes")
            if ai_enabled_env is not None
            else bool(ai_api_key or ai_base_url)
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
            base_url=ai_base_url,
            api_key=ai_api_key,
            model=ai_model,
            language=ai_lang,
            temperature=ai_temp,
            tts_enabled=tts_enabled,
            tts_model=os.getenv("AI_TTS_MODEL", "gpt-4o-mini-tts"),
            tts_voice=os.getenv("AI_TTS_VOICE", "alloy"),
        )

        # Sync / Cron
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

        sync = SyncConfig(
            output_dir=Path(output_dir_str),
            state_file=Path(state_file_str),
            interval_seconds=interval_sec,
            limit=limit,
            auto_analyze=auto_analyze,
            save_analysis_file=save_analysis,
            sport_filter=os.getenv("SYNC_SPORT_FILTER"),
            tp_email=os.getenv("TP_EMAIL") or os.getenv("TRAININGPEAKS_EMAIL"),
            smtp_host=os.getenv("SMTP_HOST"),
            smtp_port=smtp_port,
            smtp_user=os.getenv("SMTP_USER"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            smtp_from=os.getenv("SMTP_FROM"),
        )

        return cls(
            strava=strava,
            ai=ai,
            sync=sync,
            processing=ProcessingConfig(),
        )
