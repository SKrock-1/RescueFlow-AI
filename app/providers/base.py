"""
RescueFlow AI — LLM Provider Interface.

Abstract base class defining the uniform interface for LLM providers.
Hides provider-specific SDK details from the agent runner.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMResponse:
    """Standardized response container across providers."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        raw_response: Any = None,
    ) -> None:
        self.content = content or ""
        self.tool_calls = tool_calls or []
        self.raw_response = raw_response

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def __repr__(self) -> str:
        return f"<LLMResponse content_len={len(self.content)} tool_calls={len(self.tool_calls)}>"


class LLMProvider(ABC):
    """Abstract interface that all LLM providers must implement."""

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
                      (plus 'tool_calls' / 'tool_call_id' where applicable).
            tools: Optional list of OpenAI-formatted function-calling tool schemas.
            **kwargs: Extra parameters like temperature, max_tokens, etc.

        Returns:
            Standardized LLMResponse object.
        """
        pass
