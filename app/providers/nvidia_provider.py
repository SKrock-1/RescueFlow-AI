"""
RescueFlow AI — NVIDIA NIM Provider.

Uses the OpenAI-compatible client interface to interact with NVIDIA NIM microservices.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.errors import ProviderError
from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class NvidiaProvider(LLMProvider):
    """NVIDIA NIM provider utilizing OpenAI client compatibility."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.nvidia_api_key
        self.base_url = base_url or settings.nvidia_base_url
        self.model = model or settings.nvidia_model

        if not self.api_key:
            logger.warning("NVIDIA API key not configured. Calls will fail unless mocked.")

        try:
            from openai import OpenAI
            self._client = (
                OpenAI(base_url=self.base_url, api_key=self.api_key)
                if self.api_key
                else None
            )
        except ImportError:
            self._client = None
            logger.warning("openai library not installed. Install with `pip install openai`.")

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate response via NVIDIA NIM API."""
        if not self._client:
            raise ProviderError(
                "nvidia",
                "NVIDIA client not initialized. Ensure NVIDIA_API_KEY is set in .env and openai package is installed."
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
            response = self._client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            logger.exception("NVIDIA API error during chat completion")
            raise ProviderError("nvidia", str(exc)) from exc

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

        reasoning = getattr(message, "reasoning_content", None)
        if not content and reasoning and not parsed_tool_calls:
            content = reasoning

        return LLMResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            raw_response=response,
        )
