"""
RescueFlow AI — Resilient Fallback LLM Provider.

Executes sequential failover across providers (e.g., Primary ➔ Secondary ➔ Heuristic Mock).
Guarantees business continuity when encountering 429 rate limits, model deprecations, or outages.
"""

from __future__ import annotations

import logging
from typing import Any

from app.errors import ProviderError
from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Sequentially attempts candidate LLM providers until one succeeds."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ProviderError("fallback", "No active providers supplied to FallbackProvider.")

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        errors: list[str] = []
        for provider in self.providers:
            prov_ident = getattr(provider, "model", type(provider).__name__)
            try:
                return provider.generate(messages=messages, tools=tools, **kwargs)
            except Exception as exc:
                logger.warning(
                    "Provider '%s' failed with error: %s. Attempting next provider in fallback chain...",
                    prov_ident,
                    exc,
                )
                errors.append(f"[{prov_ident}]: {exc}")

        raise ProviderError(
            "fallback",
            f"All providers in fallback chain failed: {' | '.join(errors)}",
        )

