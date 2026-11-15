"""
RescueFlow AI — Agent engine selection.

Three engines run the same rescue with the same guardrails, approval gate,
verification and outcome rules:

- ``multi_agent`` (default): specialised agents (Triage, Customer Context,
  Logistics, Knowledge, Planner, Policy Critic, Execution, Verifier)
  coordinated by a Microsoft Agent Framework workflow (``app.multi_agent``).
- ``agent_framework``: one Agent Framework agent with all tools
  (``app.af.rescue_agent``), the Phase 1 baseline.
- ``legacy``: the original hand-written Plan-Act-Observe loop.
"""

from __future__ import annotations

from app.agent.agent import AgentRunner
from app.agent.observer import AgentObserver
from app.config import get_settings
from app.providers.base import LLMProvider

ENGINE_LABELS = {
    "multi_agent": "Multi-agent workflow (Agent Framework)",
    "agent_framework": "Single Agent Framework agent",
    "legacy": "Hand-written loop (baseline)",
}


def resolve_engine_name(engine: str | None = None) -> str:
    name = (engine or get_settings().agent_engine or "multi_agent").strip().lower()
    if name not in ENGINE_LABELS:
        raise ValueError(f"Unknown agent engine '{engine}'. Choose one of: {', '.join(ENGINE_LABELS)}.")
    return name


def create_runner(
    engine: str | None = None,
    provider: LLMProvider | None = None,
    max_steps: int | None = None,
    observers: list[AgentObserver] | None = None,
) -> AgentRunner:
    """Build the runner for an engine; both expose the same AgentRunner interface."""
    name = resolve_engine_name(engine)
    if name == "multi_agent":
        from app.multi_agent.workflow import MultiAgentRescue  # imported lazily: optional dependency

        return MultiAgentRescue(provider=provider, max_steps=max_steps, observers=observers)
    if name == "agent_framework":
        from app.af.rescue_agent import AFRescueAgent  # imported lazily: optional dependency

        return AFRescueAgent(provider=provider, max_steps=max_steps, observers=observers)
    return AgentRunner(provider=provider, max_steps=max_steps, observers=observers)
