"""
Domain models and data structures for Strava to TrainingPeaks.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List
import time


class Sport(Enum):
    """Supported sports enumeration."""
    BIKE = "Bike"
    RUN = "Run"
    SWIM = "Swim"
    OTHER = "Other"

    @classmethod
    def from_strava_type(cls, strava_type: str) -> "Sport":
        """Map Strava activity type string to Sport enum."""
        mapping = {
            "Ride": cls.BIKE,
            "VirtualRide": cls.BIKE,
            "EBikeRide": cls.BIKE,
            "GravelRide": cls.BIKE,
            "MountainBikeRide": cls.BIKE,
            "Run": cls.RUN,
            "VirtualRun": cls.RUN,
            "TrailRun": cls.RUN,
            "Walk": cls.RUN,
            "Hike": cls.RUN,
            "Swim": cls.SWIM,
        }
        return mapping.get(strava_type, cls.OTHER)


@dataclass
class AnalysisConfig:
    """Configuration for LLM analysis."""
    training_plan: str = ""
    language: str = "Portuguese (Brazil)"


@dataclass
class ProcessingConfig:
    """Configuration for TCX trackpoint data processing."""
    euclidean_threshold_large: float = 0.55  # > 4000 rows
    euclidean_threshold_medium: float = 0.35  # > 1000 rows
    euclidean_threshold_small: float = 0.10   # <= 1000 rows
    large_dataset_threshold: int = 4000
    medium_dataset_threshold: int = 1000


DEFAULT_REDIRECT_URI = "http://localhost:8089/callback"
DEFAULT_SCOPES = "activity:read_all"
DEFAULT_TOKEN_FILE = ".strava_tokens.json"


@dataclass
class AthleteToken:
    """Represents an athlete's OAuth tokens."""
    athlete_id: int
    athlete_name: str
    access_token: str
    refresh_token: str
    expires_at: int
    token_type: str = "Bearer"
    scopes: str = DEFAULT_SCOPES

    def is_expired(self) -> bool:
        """Check if the access token is expired with 5-minute buffer."""
        return time.time() >= (self.expires_at - 300)

    def to_dict(self) -> Dict[str, Any]:
        """Convert token to dictionary for JSON persistence."""
        return asdict(self)


@dataclass
class StravaOAuthConfig:
    """Configuration for Strava OAuth."""
    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: str = DEFAULT_SCOPES
    token_file: str = DEFAULT_TOKEN_FILE


@dataclass
class ActivitySummary:
    """Summary representation of a Strava activity."""
    id: int
    name: str
    sport: Sport
    strava_type: str
    start_date: str
    distance_meters: float = 0.0
    elapsed_time_seconds: int = 0
    moving_time_seconds: int = 0
    total_elevation_gain: float = 0.0

    @classmethod
    def from_strava_dict(cls, data: Dict[str, Any]) -> "ActivitySummary":
        raw_type = data.get("type", "Other")
        return cls(
            id=data["id"],
            name=data.get("name", f"Activity {data['id']}"),
            sport=Sport.from_strava_type(raw_type),
            strava_type=raw_type,
            start_date=data.get("start_date", datetime.now(timezone.utc).isoformat()),
            distance_meters=float(data.get("distance", 0.0)),
            elapsed_time_seconds=int(data.get("elapsed_time", 0)),
            moving_time_seconds=int(data.get("moving_time", 0)),
            total_elevation_gain=float(data.get("total_elevation_gain", 0.0)),
        )


@dataclass
class SyncResult:
    """Result of a single activity sync operation."""
    activity_id: int
    athlete_id: int
    success: bool
    tcx_path: Optional[str] = None
    analysis_path: Optional[str] = None
    analysis_text: Optional[str] = None
    error_message: Optional[str] = None
    synced_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SyncBatchSummary:
    """Summary of a sync run across all activities."""
    total_found: int = 0
    newly_synced: int = 0
    already_synced: int = 0
    failed: int = 0
    results: List[SyncResult] = field(default_factory=list)
