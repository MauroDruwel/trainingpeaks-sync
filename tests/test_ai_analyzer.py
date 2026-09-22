"""
Unit tests for universal OpenAI-compatible AIAnalyzer and TTSGenerator.
"""
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import pandas as pd

from src.ai.analyzer import AIAnalyzer
from src.ai.tts import TTSGenerator, clean_text_for_speech
from src.config import AIConfig
from src.models import Sport, AnalysisConfig


class TestAIAnalyzer(unittest.TestCase):
    """Test AI analyzer with custom OpenAI-compatible endpoints."""

    def test_get_client_custom_endpoint(self):
        config = AIConfig(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
            model="llama3.2"
        )
        analyzer = AIAnalyzer(config)

        with patch("src.ai.analyzer.openai.OpenAI") as mock_openai:
            analyzer.get_client()
            mock_openai.assert_called_once_with(
                api_key="ollama",
                base_url="http://localhost:11434/v1"
            )

    def test_analyze_dataframe_success(self):
        config = AIConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-test-key",
            model="meta-llama/llama-3.2-3b-instruct",
            temperature=0.2
        )
        analyzer = AIAnalyzer(config)

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "## Session Overview\nGreat run paced at 4:30/km."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        df = pd.DataFrame({
            "Time": ["00:00:01", "00:00:02"],
            "Speed_Kmh": [12.0, 13.0],
            "Distance_Km": [0.01, 0.02],
            "Pace": [5.0, 4.6]
        })

        with patch.object(analyzer, "get_client", return_value=mock_client):
            result = analyzer.analyze_dataframe(
                df=df,
                sport=Sport.RUN,
                plan="Zone 2 aerobic run",
                language="English"
            )

            self.assertIn("Great run paced at 4:30/km.", result)
            mock_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            self.assertEqual(call_kwargs["model"], "meta-llama/llama-3.2-3b-instruct")
            self.assertEqual(call_kwargs["temperature"], 0.2)

    def test_analyze_dataframe_handles_error(self):
        config = AIConfig(api_key="test-key")
        analyzer = AIAnalyzer(config)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Connection refused to Ollama")

        df = pd.DataFrame({"Time": ["00:00:01"], "Speed_Kmh": [12.0]})

        with patch.object(analyzer, "get_client", return_value=mock_client):
            with self.assertRaises(RuntimeError) as ctx:
                analyzer.analyze_dataframe(df, Sport.RUN)
            self.assertIn("AI analysis failed", str(ctx.exception))

    def test_clean_text_for_speech(self):
        markdown_text = """# Header 1
## Header 2
This is **bold** and *italic* text.
- Bullet 1
- Bullet 2

Multiple newlines.
"""
        cleaned = clean_text_for_speech(markdown_text)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("- Bullet", cleaned)
        self.assertIn("bold and italic text", cleaned)

    def test_tts_generator_no_api_key(self):
        config = AIConfig(api_key="")
        tts = TTSGenerator(config)

        with patch.dict("os.environ", {}, clear=True):
            result = tts.generate_audio_summary("Hello athlete")
            self.assertIsNone(result)

    def test_tts_generator_success(self, tmp_path=None):
        config = AIConfig(api_key="test-api-key")
        tts = TTSGenerator(config)

        mock_client = MagicMock()
        mock_speech_response = MagicMock()
        mock_client.audio.speech.create.return_value = mock_speech_response

        with patch("src.ai.tts.openai.OpenAI", return_value=mock_client), \
             patch("pathlib.Path.mkdir"):
            output_file = Path("/tmp/test_speech.mp3")
            result = tts.generate_audio_summary("Great training session today!", output_file)
            self.assertEqual(result, output_file)
            mock_speech_response.stream_to_file.assert_called_once()
