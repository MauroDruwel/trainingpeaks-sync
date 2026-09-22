"""
Text-to-speech audio summary generation using OpenAI-compatible audio API.
"""
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

import openai

from ..config import AIConfig


logger = logging.getLogger(__name__)


def clean_text_for_speech(text: str) -> str:
    """Clean markdown formatting and prepare text for speech synthesis."""
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'^[-*]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


class TTSGenerator:
    """Audio summary generator."""

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or AIConfig()

    def generate_audio_summary(
        self,
        text: str,
        output_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """Convert analysis text to an MP3 audio summary."""
        api_key = self.config.effective_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("API key not found. Aborting audio summary generation.")
            return None

        clean_text = clean_text_for_speech(text)
        if not clean_text:
            logger.warning("Analysis text is empty after cleaning. No audio generated.")
            return None

        if output_path is None:
            download_folder = Path.home() / "Downloads"
            download_folder.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            output_path = download_folder / f"training_analysis_summary_{timestamp}.mp3"

        try:
            kwargs = {"api_key": api_key}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url

            client = openai.OpenAI(**kwargs)
            response = client.audio.speech.create(
                model=self.config.tts_model,
                voice=self.config.tts_voice,
                input=clean_text,
                speed=1.1,
                response_format="mp3",
            )
            response.stream_to_file(str(output_path), chunk_size=1024)
            logger.info("Audio summary saved to: %s", output_path)
            return output_path

        except Exception as err:
            logger.warning("Failed to generate audio summary: %s", str(err))
            return None
