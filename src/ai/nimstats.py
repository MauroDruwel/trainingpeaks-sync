"""
NIMStats Client & Model Resolver.

Integrates with Mauro Druwel's NIMStats project (https://nimstats.maurodruwel.be/)
to dynamically query and retrieve the top-performing LLM for sports coaching analysis
on the NVIDIA NIM OpenAI-compatible API (https://integrate.api.nvidia.com/v1).
"""
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

NIMSTATS_DEFAULT_URL = "https://nimstats.maurodruwel.be"
NVIDIA_NIM_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Safe fallbacks if network is unreachable
FALLBACK_MODELS: Dict[str, str] = {
    "intelligence": "deepseek-ai/deepseek-v4.1-flash",
    "speed": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "balanced": "openai/gpt-oss-20b",
}


@dataclass
class NIMStatsModelInfo:
    """Benchmark metadata for a model from NIMStats."""
    best_model: str
    provider: str
    score: float
    intelligence: Optional[float]
    uptime: float
    avg_response_time_ms: Optional[float]
    avg_throughput_tps: Optional[float]
    strategy: str
    generated_at: str


class NIMStatsClient:
    """
    Client for querying Mauro Druwel's NIMStats API
    (https://nimstats.maurodruwel.be/top/{strategy}.json).
    """

    def __init__(
        self,
        base_url: str = NIMSTATS_DEFAULT_URL,
        cache_ttl_seconds: int = 3600,
        user_agent: str = "TrainingPeaks-Sync/2.0 (MauroDruwel)",
    ):
        self.base_url = base_url.rstrip("/")
        self.cache_ttl_seconds = cache_ttl_seconds
        self.user_agent = user_agent
        self._cache: Dict[str, Tuple[float, str, Optional[NIMStatsModelInfo]]] = {}

    def _normalize_strategy(self, strategy: str) -> str:
        s = strategy.lower().strip()
        if s in ("intel", "intelligence", "quality", "coach"):
            return "intelligence"
        if s in ("fast", "speed", "quick", "latency"):
            return "speed"
        if s in ("index", "balanced", "score", "default", "auto"):
            return "index"
        return s

    def get_best_model(
        self,
        strategy: str = "intelligence",
        timeout: float = 5.0,
        force_refresh: bool = False,
    ) -> Tuple[str, Optional[NIMStatsModelInfo]]:
        """
        Fetch the best model for a given strategy ('intelligence', 'speed', or 'balanced').
        Caches results for `cache_ttl_seconds` to minimize network overhead.
        """
        norm_strat = self._normalize_strategy(strategy)
        endpoint_slug = "index" if norm_strat in ("balanced", "index") else norm_strat

        # Check cache
        now = time.time()
        if not force_refresh and endpoint_slug in self._cache:
            cached_time, cached_model, cached_info = self._cache[endpoint_slug]
            if now - cached_time < self.cache_ttl_seconds:
                return cached_model, cached_info

        url = f"{self.base_url}/top/{endpoint_slug}.json"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            best_model = data.get("best_model")
            if not best_model:
                raise ValueError(f"No 'best_model' found in response from {url}")

            info = NIMStatsModelInfo(
                best_model=best_model,
                provider=data.get("provider", ""),
                score=float(data.get("score", 0)),
                intelligence=float(data["intelligence"]) if data.get("intelligence") is not None else None,
                uptime=float(data.get("uptime", 0)),
                avg_response_time_ms=float(data["avg_response_time_ms"]) if data.get("avg_response_time_ms") is not None else None,
                avg_throughput_tps=float(data["avg_throughput_tps"]) if data.get("avg_throughput_tps") is not None else None,
                strategy=strategy,
                generated_at=data.get("generated_at", ""),
            )

            self._cache[endpoint_slug] = (now, best_model, info)
            logger.info(
                "Retrieved best NIMStats model for '%s': %s (Score: %s, Intel: %s, Uptime: %s%%)",
                strategy,
                best_model,
                info.score,
                info.intelligence,
                info.uptime,
            )
            return best_model, info

        except Exception as err:
            logger.warning(
                "Failed to fetch model from NIMStats (%s): %s. Using fallback.",
                url,
                err,
            )
            fallback = FALLBACK_MODELS.get(norm_strat, "deepseek-ai/deepseek-v4.1-flash")
            return fallback, None

    def get_all_strategies(self, timeout: float = 5.0) -> Dict[str, Tuple[str, Optional[NIMStatsModelInfo]]]:
        """Fetch all three strategy models: intelligence, balanced, speed."""
        results = {}
        for strat in ("intelligence", "balanced", "speed"):
            results[strat] = self.get_best_model(strat, timeout=timeout)
        return results


_default_nimstats_client: Optional[NIMStatsClient] = None


def get_nimstats_client(base_url: Optional[str] = None) -> NIMStatsClient:
    """Return singleton NIMStats client."""
    global _default_nimstats_client
    if _default_nimstats_client is None or (base_url and _default_nimstats_client.base_url != base_url.rstrip("/")):
        _default_nimstats_client = NIMStatsClient(base_url=base_url or NIMSTATS_DEFAULT_URL)
    return _default_nimstats_client
