"""
Sync state persistence and history tracking.
Ensures activities are synced once and not redundantly processed.
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List


logger = logging.getLogger(__name__)


class SyncStateManager:
    """Manages persistent record of synced activities to enable idempotent cron runs."""

    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self._state: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load state from JSON file."""
        if not self.state_file.exists():
            return {
                "version": 1,
                "last_sync": None,
                "synced_activities": {}
            }

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return {"version": 1, "last_sync": None, "synced_activities": {}}
                return json.loads(content)
        except Exception as err:
            logger.warning("Could not parse sync state file %s: %s. Starting fresh.", self.state_file, err)
            return {"version": 1, "last_sync": None, "synced_activities": {}}

    def save(self) -> None:
        """Atomically persist state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=self.state_file.parent,
            prefix=".sync_state_",
            suffix=".tmp"
        )
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(self._state, f, indent=2)
            os.replace(temp_path, self.state_file)
        except Exception as err:
            logger.error("Failed to save sync state to %s: %s", self.state_file, err)
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def is_synced(self, activity_id: int) -> bool:
        """Check if an activity has already been processed."""
        return str(activity_id) in self._state.get("synced_activities", {})

    def get_synced_activity(self, activity_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve stored details for a previously synced activity."""
        return self._state.get("synced_activities", {}).get(str(activity_id))

    def record_synced(
        self,
        activity_id: Any,
        athlete_id: Optional[int],
        name: str,
        sport: str,
        start_date: str,
        tcx_path: str,
        analyzed: bool = False,
        analysis_path: Optional[str] = None,
        sources: Optional[List[str]] = None,
        has_watch_data: bool = True,
    ) -> None:
        """Record activity as successfully synced and persist state."""
        if "synced_activities" not in self._state:
            self._state["synced_activities"] = {}

        now_iso = datetime.now(timezone.utc).isoformat()
        self._state["synced_activities"][str(activity_id)] = {
            "athlete_id": athlete_id,
            "name": name,
            "sport": sport,
            "start_date": start_date,
            "tcx_path": tcx_path,
            "synced_at": now_iso,
            "analyzed": analyzed,
            "analysis_path": analysis_path,
            "sources": sources or ["strava"],
            "has_watch_data": has_watch_data,
        }
        self._state["last_sync"] = now_iso
        self.save()

    def get_last_sync(self) -> Optional[str]:
        """Return ISO timestamp of the last successful sync run."""
        return self._state.get("last_sync")

    def get_total_synced_count(self) -> int:
        """Return total number of activities synced."""
        return len(self._state.get("synced_activities", {}))

    def get_all_synced_activities(self) -> Dict[str, Any]:
        """Return full dictionary of all recorded activities."""
        return dict(self._state.get("synced_activities", {}))
