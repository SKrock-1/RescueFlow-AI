"""
RescueFlow AI — Groq Provider.

Connects to the Groq API for ultra-low latency inference using models
like Llama 3.3 70B Versatile.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import get_settings
from app.errors import ProviderError
from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


MAX_SHORT_WAIT_SECONDS = 6.0
_RETRY_AFTER = re.compile(r"try again in ([0-9.]+)\s*(ms|s)", re.I)


def retry_after_seconds(message: str) -> float | None:
    """Seconds Groq asks us to wait on a 429, or None when it does not say."""
    if "429" not in message and "rate limit" not in message.lower():
        return None
    match = _RETRY_AFTER.search(message)
    if not match:
        return None
    value = float(match.group(1))
    return value / 1000 if match.group(2).lower() == "ms" else value


class GroqProvider(LLMProvider):
    """Groq API provider implementation."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model

        if not self.api_key:
            logger.warning("Groq API key not configured. Calls will fail unless mocked.")

        try:
            from groq import Groq
            self._client = (
                Groq(api_key=self.api_key, timeout=settings.llm_timeout_seconds, max_retries=0)
                if self.api_key
                else None
            )
        except ImportError:
            self._client = None
            logger.warning("groq library not installed. Install with `pip install groq`.")

    def _create_with_short_wait(self, call_kwargs: dict[str, Any]):
        """Retry once when Groq says a per-minute limit frees up within a few seconds."""
        try:
            return self._client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            wait = retry_after_seconds(str(exc))
            if wait is None or wait > MAX_SHORT_WAIT_SECONDS:
                raise
            logger.info("Groq per-minute limit reached; waiting %.1fs and retrying once.", wait)
            time.sleep(wait + 0.25)
            return self._client.chat.completions.create(**call_kwargs)

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate response via Groq API."""
        if not self._client:
            raise ProviderError(
                "groq",
                "Groq client not initialized. Ensure GROQ_API_KEY is set in .env and groq package is installed."
            )

        call_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.1),
        }

        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = kwargs.get("tool_choice", "auto")

        try:
            response = self._create_with_short_wait(call_kwargs)
        except Exception as exc:
            exc_str = str(exc)
            # Automatic fallback if primary model hits Groq rate limit (429 / TPD limit)
            if ("429" in exc_str or "rate_limit" in exc_str or "Rate limit reached" in exc_str) and call_kwargs.get("model") != "openai/gpt-oss-20b":
                logger.warning(
                    "Groq rate limit hit on model '%s'. Automatically falling back to 'openai/gpt-oss-20b'...",
                    call_kwargs.get("model")
                )
                try:
                    fallback_kwargs = dict(call_kwargs)
                    fallback_kwargs["model"] = "openai/gpt-oss-20b"
                    response = self._client.chat.completions.create(**fallback_kwargs)
                except Exception as fb_exc:
                    logger.exception("Groq fallback model also failed")
                    raise ProviderError("groq", f"Fallback error: {fb_exc}") from fb_exc
            else:
                logger.exception("Groq API error during chat completion")
                raise ProviderError("groq", exc_str) from exc

        choice = response.choices[0]
        message = choice.message
        content = message.content or ""

        parsed_tool_calls: list[dict[str, Any]] = []
        if getattr(message, "tool_calls", None):
            for tc in message.tool_calls:
                fn_args = tc.function.arguments
                if isinstance(fn_args, str):
                    try:
                        args_dict = json.loads(fn_args)
                    except json.JSONDecodeError:
                        args_dict = {"raw_args": fn_args}
                else:
                    args_dict = fn_args or {}

                parsed_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": args_dict,
                    },
                })

        return LLMResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            raw_response=response,
        )
