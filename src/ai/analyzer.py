"""
OpenAI-compatible AI Training Analyzer.
Supports any OpenAI-compatible endpoint (OpenAI, Ollama, LM Studio, vLLM, OpenRouter, Groq, DeepSeek, LocalAI).
"""
import logging
import os
from typing import Optional

import openai
import pandas as pd
from tcxreader.tcxreader import TCXReader

from ..config import AIConfig
from ..models import Sport, AnalysisConfig
from ..tcx.processor import TrackpointProcessor


logger = logging.getLogger(__name__)

DEFAULT_ANALYSIS_SYSTEM_PROMPT = """You are an expert endurance sports coach, physiologist, and training data analyst.
Your goal is to provide clear, actionable insights on the athlete's training session.
Format your output cleanly in Markdown with concise sections."""

ANALYSIS_USER_TEMPLATE = """Please analyze this training session data for {sport} and provide a performance report in {language}.
Keep the output concise, structured, and focused on key training metrics and physiological takeaways.

# Required Sections
1. **Session Overview**: Brief summary of training type, total load, and primary stimulus.
2. **Performance Metrics**: Key trends in pace/speed, heart rate zones, power, and cadence (if available).
3. **Physiological Analysis**: Cardiovascular efficiency, pacing execution, and fatigue patterns.
4. **Key Strengths**: Top 2-3 positive execution highlights with data.
5. **Areas for Improvement**: Specific inefficiencies or adjustments for subsequent sessions.
{plan_section}
## Training Session Data
```csv
{training_data}
```
"""


class AIAnalyzer:
    """Universal OpenAI-compatible training session analyzer."""

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or AIConfig()
        self.trackpoint_processor = TrackpointProcessor()

    def get_client(self) -> openai.OpenAI:
        """Create and return configured OpenAI client."""
        base_url = self.config.base_url or os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        api_key = self.config.effective_api_key or os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or "not-needed"

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        return openai.OpenAI(**kwargs)

    def analyze(
        self,
        tcx_data: TCXReader,
        sport: Sport,
        analysis_config: Optional[AnalysisConfig] = None,
    ) -> str:
        """Run training analysis on TCX data using the configured model."""
        plan = analysis_config.training_plan if analysis_config else ""
        language = analysis_config.language if analysis_config else self.config.language

        # Preprocess trackpoints to reduce size
        processed_df = self.trackpoint_processor.process(tcx_data)
        return self.analyze_dataframe(processed_df, sport, plan, language)

    def analyze_dataframe(
        self,
        df: pd.DataFrame,
        sport: Sport,
        plan: str = "",
        language: str = "English",
    ) -> str:
        """Run training analysis directly on preprocessed DataFrame."""
        csv_data = df.to_csv(index=False)
        plan_section = ""
        if plan.strip():
            plan_section = f"\n### Planned Workout Details:\n{plan}\n- Compare actual execution against this plan.\n"

        prompt = ANALYSIS_USER_TEMPLATE.format(
            sport=sport.value,
            language=language or self.config.language,
            plan_section=plan_section,
            training_data=csv_data,
        )

        model_name = self.config.model or "gpt-4o-mini"
        logger.info(
            "Requesting AI analysis using model '%s' (endpoint: %s)",
            model_name,
            self.config.base_url or "default OpenAI"
        )

        try:
            client = self.get_client()
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": DEFAULT_ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.config.temperature,
                timeout=120,
            )

            content = response.choices[0].message.content or ""
            return content.strip()

        except Exception as err:
            logger.error("AI analysis failed: %s", str(err))
            raise RuntimeError(f"AI analysis failed: {err}") from err
