"""
RescueFlow AI — Resilient Fallback LLM Provider.

Executes sequential failover across providers (e.g., Primary ➔ Secondary ➔ Heuristic Mock).
Guarantees business continuity when encountering 429 rate limits, model deprecations, or outages.

A provider that fails is put on a short cool-down, so the next call (for
example the next agent in a multi-agent run) goes straight to a working
provider instead of waiting for the same timeout again.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.errors import ProviderError
from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 120.0
RATE_LIMIT_COOLDOWN_SECONDS = 30.0


def provider_label(provider: LLMProvider) -> str:
    """Short name of a provider for traces: the model name, or 'offline rules' for mocks."""
    name = type(provider).__name__
    if "Mock" in name:
        return "offline rules"
    return str(getattr(provider, "model", None) or name)


class FallbackProvider(LLMProvider):
    """Sequentially attempts candidate LLM providers until one succeeds."""

    def __init__(
        self,
        providers: list[LLMProvider],
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ProviderError("fallback", "No active providers supplied to FallbackProvider.")
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._cooling_until: dict[int, float] = {}
        self.last_answered_by: str | None = None

    def _is_cooling(self, index: int) -> bool:
        return self._cooling_until.get(index, 0.0) > self._clock()

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        errors: list[str] = []
        ready = [i for i in range(len(self.providers)) if not self._is_cooling(i)]
        # If every provider is cooling down, try them all rather than fail without trying.
        order = ready or list(range(len(self.providers)))
        for index in order:
            provider = self.providers[index]
            prov_ident = getattr(provider, "model", type(provider).__name__)
            try:
                response = provider.generate(messages=messages, tools=tools, **kwargs)
                self._cooling_until.pop(index, None)
                self.last_answered_by = provider_label(provider)
                return response
            except Exception as exc:
                text = str(exc).lower()
                # Per-minute rate limits clear quickly; timeouts and outages do not.
                cooldown = min(self.cooldown_seconds, RATE_LIMIT_COOLDOWN_SECONDS) if (
                    "429" in text or "rate limit" in text or "rate_limit" in text) else self.cooldown_seconds
                self._cooling_until[index] = self._clock() + cooldown
                logger.warning(
                    "Provider '%s' failed (%s); skipping it for %.0fs and trying the next provider.",
                    prov_ident,
                    exc,
                    cooldown,
                )
                errors.append(f"[{prov_ident}]: {exc}")

        raise ProviderError(
            "fallback",
            f"All providers in fallback chain failed: {' | '.join(errors)}",
        )
