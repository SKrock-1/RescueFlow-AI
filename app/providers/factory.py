"""
RescueFlow AI — LLM Provider Factory.

Instantiates and configures the appropriate LLM provider based on settings or explicit choice.
"""

from __future__ import annotations

import logging
from typing import Literal

from app.config import get_settings
from app.errors import ProviderError
from app.providers.base import LLMProvider
from app.providers.groq_provider import GroqProvider
from app.providers.nvidia_provider import NvidiaProvider
from app.providers.mock_provider import MockProvider
from app.providers.fallback_provider import FallbackProvider

logger = logging.getLogger(__name__)


def create_fallback_chain() -> FallbackProvider:
    """Creates an ordered fallback chain: Nvidia ➔ Groq ➔ Deterministic Mock."""
    chain: list[LLMProvider] = []
    settings = get_settings()

    # Prioritize based on .env primary provider setting
    if settings.llm_provider.lower().strip() == "groq":
        candidates = [GroqProvider, NvidiaProvider]
    else:
        candidates = [NvidiaProvider, GroqProvider]

    for cls in candidates:
        try:
            chain.append(cls())
        except Exception as exc:
            logger.debug("Skipping unconfigured provider %s: %s", cls.__name__, exc)

    # Always append MockProvider as final fail-safe
    chain.append(MockProvider())
    return FallbackProvider(chain)


def create_provider(
    provider_name: Literal["groq", "nvidia", "mock", "auto", "fallback"] | str | None = None
) -> LLMProvider:
    """Factory function to get an LLM provider.

    Args:
        provider_name: 'groq', 'nvidia', 'mock', or 'auto'/'fallback'. Defaults to setting in .env.

    Returns:
        Instance of LLMProvider.
    """
    settings = get_settings()
    name = (provider_name or settings.llm_provider).lower().strip()

    logger.info("Initializing LLM provider: %s", name)

    if name in ("auto", "fallback"):
        return create_fallback_chain()
    elif name == "groq":
        return GroqProvider()
    elif name == "nvidia":
        return NvidiaProvider()
    elif name == "mock":
        return MockProvider()
    else:
        raise ProviderError(
            name,
            f"Unsupported provider '{name}'. Valid options: 'groq', 'nvidia', 'mock', 'auto'."
        )
