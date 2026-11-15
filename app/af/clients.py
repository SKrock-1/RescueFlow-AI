"""
RescueFlow AI — Chat clients for Microsoft Agent Framework.

``ProviderChatClient`` lets an Agent Framework ``Agent`` talk to the
existing RescueFlow providers (NVIDIA NIM, Groq, the offline mock and the
failover chain that ties them together). Agent Framework owns the agent
loop, tool calling and middleware; the provider layer keeps its tested
429/timeout failover. Converting between the two message formats is the
only work done here.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationConfiguration,
    FunctionInvocationLayer,
    Message,
)

from app.providers.base import LLMProvider
from app.providers.factory import create_provider


def _text_of(message: Message) -> str:
    return "".join(c.text or "" for c in message.contents if c.type == "text")


def to_provider_messages(messages: Sequence[Message], instructions: str | None = None) -> list[dict[str, Any]]:
    """Agent Framework messages -> OpenAI-style dicts the providers accept."""
    out: list[dict[str, Any]] = []
    if instructions:
        out.append({"role": "system", "content": instructions})
    for msg in messages:
        role = str(msg.role)
        calls = [c for c in msg.contents if c.type == "function_call"]
        results = [c for c in msg.contents if c.type == "function_result"]
        if results:
            for r in results:
                out.append({
                    "role": "tool",
                    "tool_call_id": r.call_id,
                    "content": r.result if isinstance(r.result, str) else json.dumps(r.result, default=str),
                })
            continue
        if calls:
            out.append({
                "role": "assistant",
                "content": _text_of(msg) or None,
                "tool_calls": [
                    {
                        "id": c.call_id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.arguments if isinstance(c.arguments, str)
                            else json.dumps(c.arguments or {}),
                        },
                    }
                    for c in calls
                ],
            })
            continue
        out.append({"role": role, "content": _text_of(msg)})
    return out


class ProviderChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Agent Framework chat client backed by a RescueFlow ``LLMProvider``."""

    def __init__(
        self,
        provider: LLMProvider,
        tool_schemas: list[dict[str, Any]],
        max_iterations: int = 10,
    ) -> None:
        super().__init__(
            function_invocation_configuration=FunctionInvocationConfiguration(
                max_iterations=max_iterations,
                allow_concurrent_invocation=False,
            )
        )
        self.provider = provider
        self.tool_schemas = tool_schemas
        self.turns = 0
        self.last_assistant_text = ""

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:
            raise NotImplementedError("Streaming is not used by RescueFlow agents.")
        self.turns += 1
        instructions = options.get("instructions") if isinstance(options, dict) else None
        response = self.provider.generate(
            messages=to_provider_messages(messages, instructions),
            tools=self.tool_schemas or None,
            temperature=0.1,
        )
        contents: list[Content] = []
        text = (response.content or "").strip()
        self.last_assistant_text = text
        if text:
            contents.append(Content.from_text(text))
        for tc in response.tool_calls or []:
            contents.append(Content.from_function_call(
                call_id=tc["id"],
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            ))
        if not contents:
            contents.append(Content.from_text(""))
        return ChatResponse(messages=[Message(role="assistant", contents=contents)], response_id=f"turn-{self.turns}")


def build_chat_client(
    provider: LLMProvider | str | None,
    tool_schemas: list[dict[str, Any]],
    max_iterations: int = 10,
) -> ProviderChatClient:
    """Wrap a provider instance or name ('auto', 'groq', 'nvidia', 'mock')."""
    if provider is None or isinstance(provider, str):
        provider = create_provider(provider) if provider else create_provider()
    return ProviderChatClient(provider, tool_schemas, max_iterations=max_iterations)
