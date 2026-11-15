"""
RescueFlow AI — Rescue agent built on Microsoft Agent Framework.

Phase 1 of the multi-agent plan: the same single-agent rescue as
``AgentRunner``, but the loop, tool calling and the tool pipeline are run by
Agent Framework (``Agent``, ``FunctionTool``, ``FunctionMiddleware``).

What stays shared with the hand-written engine (so both behave the same):
claiming the incident, guardrails, the plan-only approval gate,
verification, outcome rules, memory and notifications. They live on
``AgentRunner`` and are called from ``RescueToolMiddleware``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from typing import Any, Coroutine

from agent_framework import (
    Agent,
    FunctionInvocationContext,
    FunctionMiddleware,
    FunctionTool,
    MiddlewareTermination,
)

from app.af.clients import ProviderChatClient, build_chat_client
from app.agent.agent import AgentRunner, RunContext
from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.schemas.models import AgentResult
from app.tools.registry import registry

logger = logging.getLogger(__name__)

AGENT_NAME = "rescueflow_resolver"


def build_tools() -> list[FunctionTool]:
    """Every registered RescueFlow tool as an Agent Framework FunctionTool."""
    tools: list[FunctionTool] = []
    for spec in registry.get_openai_tools():
        fn = spec["function"]
        tools.append(FunctionTool(
            name=fn["name"],
            description=fn.get("description", ""),
            func=registry.get_tool(fn["name"]),
            input_model=fn.get("parameters") or {"type": "object", "properties": {}},
        ))
    return tools


def _as_dict(result: Any) -> dict[str, Any]:
    """Tool results come back as list[Content] or str; recover the tool's dict."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        result = "".join(getattr(c, "text", None) or str(getattr(c, "result", "") or "") for c in result)
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            return parsed if isinstance(parsed, dict) else {"success": True, "result": parsed}
        except json.JSONDecodeError:
            return {"success": True, "result": result}
    return {"success": True, "result": result}


class RescueToolMiddleware(FunctionMiddleware):
    """Runs RescueFlow's guardrails, approval gate and verification around each tool call."""

    def __init__(self, runner: AgentRunner, ctx: RunContext, client: ProviderChatClient) -> None:
        self.runner = runner
        self.ctx = ctx
        self.client = client

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        name = context.function.name
        raw_args = context.arguments
        args = raw_args.model_dump() if hasattr(raw_args, "model_dump") else dict(raw_args or {})
        self.ctx.step_counter = self.client.turns
        assistant_text = self.client.last_assistant_text

        decision, blocked_output = self.runner._before_tool(self.ctx, name, args, assistant_text)
        if decision == "propose":
            raise MiddlewareTermination(
                "Proposal stored for operator approval.",
                result=json.dumps({"success": True, "status": "PROPOSED",
                                   "message": "Waiting for operator approval."}),
            )

        if decision == "block":
            output = blocked_output or {"success": False}
            context.result = json.dumps(output)
        else:
            try:
                await call_next()
                output = _as_dict(context.result)
            except MiddlewareTermination:
                raise
            except Exception as exc:  # a tool raised: report it to the model like the legacy loop
                output = {"success": False, "error": str(exc)}
                self.ctx.state.errors.append(str(exc))
                context.result = json.dumps(output)

        if self.runner._after_tool(self.ctx, name, args, output, assistant_text):
            raise MiddlewareTermination("Escalated to human operations; the run ends.", result=json.dumps(output))


def _run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine from sync code (Streamlit script thread, FastAPI worker, tests)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class AFRescueAgent(AgentRunner):
    """Single rescue agent on Microsoft Agent Framework (engine 'agent_framework')."""

    engine_name = "agent_framework"

    def resolve_incident(self, incident_id: int, plan_only: bool = False) -> AgentResult:
        ctx = self._open_run(incident_id, plan_only)
        client = build_chat_client(self.provider, registry.get_openai_tools(), max_iterations=self.max_steps)
        agent = Agent(
            client=client,
            instructions=AGENT_SYSTEM_PROMPT,
            name=AGENT_NAME,
            description="Investigates a failed delivery and resolves, proposes or escalates it.",
            tools=build_tools(),
            middleware=[RescueToolMiddleware(self, ctx, client)],
        )

        try:
            response = _run_sync(agent.run(self._incident_prompt(ctx)))
        except Exception as exc:
            logger.exception("Agent Framework run failed for incident %d", incident_id)
            ctx.step_counter = client.turns
            self._provider_failed(ctx, exc)
        else:
            ctx.step_counter = client.turns
            finished_by_tool = ctx.proposed_action is not None or ctx.action_name_taken == "escalate_incident"
            if not finished_by_tool:
                # The final turn's text is the decision; response.text joins every turn.
                text = client.last_assistant_text or (response.text or "").strip()
                if text:
                    self._record_decision(ctx, text)
        return self._close_run(ctx)
