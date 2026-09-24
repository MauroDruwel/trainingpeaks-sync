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

    def upload_tcx(self, tcx_path: Path) -> bool:
        """
        Upload a TCX activity file to Garmin Connect.
        When connected, Garmin Connect automatically forwards the workout to TrainingPeaks.
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
            return True
        except Exception as err:
            err_msg = str(err).lower()
            if "409" in err_msg or "conflict" in err_msg or "already" in err_msg or "exists" in err_msg:
                logger.info("Activity %s already exists in Garmin Connect.", tcx_path.name)
                return True
            logger.error("Failed to upload %s to Garmin Connect: %s", tcx_path.name, err)
            return False
