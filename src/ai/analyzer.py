"""
OpenAI-compatible AI Training Analyzer.
Supports any OpenAI-compatible endpoint (OpenAI, Ollama, LM Studio, vLLM, OpenRouter, Groq, DeepSeek, LocalAI).
"""
import logging
import os
from typing import Optional, Tuple

import openai
import pandas as pd
from tcxreader.tcxreader import TCXReader

from ..config import AIConfig
from ..models import Sport, AnalysisConfig
from ..tcx.processor import TrackpointProcessor
from .nimstats import get_nimstats_client, NIMStatsModelInfo


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
    """Universal OpenAI-compatible training session analyzer with NIMStats best-model retrieval."""

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or AIConfig()
        self.trackpoint_processor = TrackpointProcessor()

    def resolve_model(self) -> Tuple[str, Optional[NIMStatsModelInfo]]:
        """
        Resolve the model to use for analysis.
        If configured to 'auto', 'nimstats', 'best', or if using NVIDIA NIM with NIMStats enabled,
        retrieves the top model from Mauro Druwel's NIMStats API (https://nimstats.maurodruwel.be).
        """
        raw_model = (self.config.model or "auto").strip()

        # Check if model explicitly specifies strategy (e.g. 'nimstats:intelligence' or 'nimstats:speed')
        strategy = self.config.nimstats_strategy
        if raw_model.startswith("nimstats:"):
            strategy = raw_model.split(":", 1)[1]
            raw_model = "auto"

        should_query_nimstats = (
            raw_model in ("auto", "nimstats", "best")
            or (self.config.is_nvidia_nim and self.config.nimstats_enabled and raw_model in ("auto", "nimstats", "best", "gpt-4o-mini"))
        )

        if should_query_nimstats and self.config.nimstats_enabled:
            client = get_nimstats_client(base_url=self.config.nimstats_url)
            model_name, info = client.get_best_model(strategy=strategy)
            if info:
                logger.info(
                    "Selected top model '%s' from NIMStats (%s strategy, score: %s, intel: %s, uptime: %s%%)",
                    model_name,
                    info.strategy,
                    info.score,
                    info.intelligence,
                    info.uptime,
                )
            else:
                logger.info("Selected model '%s' via NIMStats fallback for '%s'", model_name, strategy)
            return model_name, info

        return raw_model, None

    def get_client(self) -> openai.OpenAI:
        """Create and return configured OpenAI client."""
        base_url = self.config.effective_base_url
        api_key = self.config.effective_api_key or "not-needed"

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

        model_name, nim_info = self.resolve_model()
        logger.info(
            "Requesting AI analysis using model '%s' (endpoint: %s)",
            model_name,
            self.config.effective_base_url or "default OpenAI"
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

            content = (response.choices[0].message.content or "").strip()
            if nim_info:
                footer = f"\n\n---\n*⚡ AI Coaching generated via NVIDIA NIM (`{model_name}`) · Model selected by [NIMStats](https://nimstats.maurodruwel.be/) (Strategy: {nim_info.strategy}, Intel: {nim_info.intelligence})*"
                content += footer

            return content

        except Exception as err:
            logger.error("AI analysis failed: %s", str(err))
            raise RuntimeError(f"AI analysis failed: {err}") from err
