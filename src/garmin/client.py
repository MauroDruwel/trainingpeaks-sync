"""
Garmin Connect uploader for automated workout bridging.
Uploads TCX files to Garmin Connect, which automatically syncs to TrainingPeaks
via Garmin's official TrainingPeaks integration.
"""
import logging
from pathlib import Path
from typing import Optional, Tuple, Callable

from ..config import GarminConfig

logger = logging.getLogger(__name__)


class GarminUploader:
    """Handles authentication and activity uploading to Garmin Connect."""

    def __init__(self, config: GarminConfig, prompt_mfa: Optional[Callable[[], str]] = None):
        self.config = config
        self.prompt_mfa = prompt_mfa
        self._client = None

    def is_configured(self) -> bool:
        """Check if Garmin Connect credentials or saved tokens exist."""
        return self.config.is_configured

    def _get_client(self, interactive: bool = False):
        """Get or initialize authenticated GarminConnect client."""
        if self._client is not None:
            return self._client

        from garminconnect import Garmin

        tokenstore = str(Path(self.config.token_file).resolve())

        mfa_handler = self.prompt_mfa
        if not mfa_handler and interactive:
            mfa_handler = lambda: input("Enter Garmin 6-digit MFA verification code: ").strip()

        client = Garmin(
            email=self.config.email,
            password=self.config.password,
            prompt_mfa=mfa_handler,
        )
        client.login(tokenstore=tokenstore)
        self._client = client
        return client

    def test_connection(self, interactive: bool = False) -> Tuple[bool, str]:
        """Verify Garmin Connect authentication and print user profile info."""
        if not self.is_configured():
            return False, "Garmin Connect not configured (set GARMIN_EMAIL and GARMIN_PASSWORD in .env)."

        try:
            client = self._get_client(interactive=interactive)
            full_name = client.get_full_name() or self.config.email or "Garmin User"
            return True, f"Successfully authenticated to Garmin Connect as '{full_name}'."
        except Exception as err:
            return False, f"Garmin Connect authentication failed: {err}"

    def upload_tcx(
        self,
        tcx_path: Path,
        title: Optional[str] = None,
        sport: Optional[str] = None,
        start_time: Optional[object] = None,
    ) -> bool:
        """
        Upload a TCX activity file to Garmin Connect.
        When connected, Garmin Connect automatically forwards the workout to TrainingPeaks.
        Also categorizes activity (e.g. swimming) and sets the activity name.
        """
        if not self.is_configured():
            logger.debug("Garmin Connect upload not configured, skipping.")
            return False

        tcx_path = Path(tcx_path)
        if not tcx_path.is_file():
            logger.error("TCX file does not exist: %s", tcx_path)
            return False

        try:
            client = self._get_client(interactive=False)
            logger.info("Uploading %s to Garmin Connect...", tcx_path.name)
            client.upload_activity(str(tcx_path))
            logger.info(
                "Successfully uploaded %s to Garmin Connect -> auto-syncing to TrainingPeaks!",
                tcx_path.name,
            )

            # Automatically categorize activity in Garmin Connect (e.g. swimming) and apply title
            try:
                import time
                target_act = None
                for _ in range(3):
                    time.sleep(2.0)
                    recent_acts = client.get_activities(0, 5)
                    if not recent_acts:
                        continue
                    if start_time:
                        from datetime import datetime
                        if isinstance(start_time, datetime):
                            date_str = start_time.strftime("%Y-%m-%d")
                            time_str = start_time.strftime("%H:%M")
                        else:
                            date_str = str(start_time)[:10]
                            time_str = str(start_time)[11:16] if len(str(start_time)) >= 16 else ""

                        for act in recent_acts:
                            act_local = str(act.get("startTimeLocal") or "")
                            act_gmt = str(act.get("startTimeGMT") or "")
                            if (date_str in act_local and time_str in act_local) or (date_str in act_gmt and time_str in act_gmt):
                                target_act = act
                                break
                            elif date_str in act_local or date_str in act_gmt:
                                target_act = act
                    else:
                        target_act = recent_acts[0]

                    if target_act:
                        break

                if target_act:
                    aid = target_act.get("activityId")
                    if aid:
                        sport_str = str(sport).lower() if sport else "swim"
                        if "swim" in sport_str:
                            client.set_activity_type(str(aid), type_id=26, type_key="swimming", parent_type_id=17)
                            logger.info("Categorized Garmin activity %s as swimming", aid)
                        elif "run" in sport_str:
                            client.set_activity_type(str(aid), type_id=1, type_key="running", parent_type_id=17)
                        elif "bike" in sport_str or "ride" in sport_str:
                            client.set_activity_type(str(aid), type_id=2, type_key="cycling", parent_type_id=17)

                        if title:
                            client.set_activity_name(str(aid), title)
                            logger.info("Set Garmin activity %s title to '%s'", aid, title)
            except Exception as cat_err:
                logger.warning("Could not set activity category/title on Garmin Connect: %s", cat_err)

            return True
        except Exception as err:
            err_msg = str(err).lower()
            if "409" in err_msg or "conflict" in err_msg or "already" in err_msg or "exists" in err_msg:
                logger.info("Activity %s already exists in Garmin Connect.", tcx_path.name)
                return True
            if "consent" in err_msg or "412" in err_msg:
                logger.error(
                    "Failed to upload %s to Garmin Connect: EU Upload Consent is required. "
                    "Please log into https://connect.garmin.com once and accept 'Storage & Processing' / 'Device Upload' in Profile & Privacy settings.",
                    tcx_path.name,
                )
                return False
            logger.error("Failed to upload %s to Garmin Connect: %s", tcx_path.name, err)
            return False
