"""
RescueFlow AI — Engine parity tests.

Every scenario runs on both engines: the hand-written baseline loop and the
Microsoft Agent Framework agent. Both must reach the same outcome, store the
same proposals, and respect the same guardrails.
"""

from __future__ import annotations

import pytest

from app.agent.engines import create_runner
from app.database.engine import get_db
from app.database.models import AgentRun, Delivery
from app.providers.base import LLMProvider, LLMResponse
from app.services.guardrails import policy_violation

ENGINES = ["legacy", "agent_framework"]


def _call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


class Scripted(LLMProvider):
    """Returns the scripted responses in order, then a closing text."""

    def __init__(self, *responses: LLMResponse):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def generate(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Done.")


def reschedule(order_id=1, start="09:00", end="12:00"):
    return LLMResponse(content="Reschedule to the morning window.", tool_calls=[_call("r", "reschedule_delivery", {
        "order_id": order_id, "date": "2026-12-01", "start_time": start, "end_time": end})])


def get_order(order_id=1):
    return LLMResponse(content="Inspecting order.", tool_calls=[_call("g", "get_order", {"order_id": order_id})])


def escalate(order_id, reason="Cannot recover."):
    return LLMResponse(content="Escalating.", tool_calls=[_call("e", "escalate_incident", {"order_id": order_id, "reason": reason})])


@pytest.mark.parametrize("engine", ENGINES)
def test_reschedule_is_resolved_and_verified(engine):
    provider = Scripted(get_order(), reschedule(), LLMResponse(content="Rescheduled for 2026-12-01 09:00-12:00."))
    result = create_runner(engine, provider=provider, max_steps=6).resolve_incident(1)

    assert result.status == "RESOLVED"
    assert result.action_taken == "reschedule_delivery"
    assert result.decision_summary == "Rescheduled for 2026-12-01 09:00-12:00."
    kinds = [e.event_type for e in result.trace]
    assert kinds.count("tool_call") == 2 and "verification" in kinds
    with get_db() as db:
        assert str(db.query(Delivery).filter(Delivery.order_id == 1).first().scheduled_date) == "2026-12-01"
        stored = db.query(AgentRun).filter(AgentRun.incident_id == 1, AgentRun.action_type == "verification").count()
    assert stored == 1


@pytest.mark.parametrize("engine", ENGINES)
def test_plan_only_stops_at_the_first_change(engine):
    provider = Scripted(get_order(), reschedule(order_id=2))
    result = create_runner(engine, provider=provider, max_steps=6).resolve_incident(1, plan_only=True)

    assert result.status == "AWAITING_APPROVAL"
    assert result.proposed_action["tool_name"] == "reschedule_delivery"
    assert result.proposed_action["arguments"]["order_id"] == 1  # pinned to the incident's order
    assert result.decision_summary == "Reschedule to the morning window."
    assert len(provider.calls) == 2  # no model call after the proposal
    with get_db() as db:
        assert db.query(Delivery).filter(Delivery.order_id == 1).first().status == "FAILED"


@pytest.mark.parametrize("engine", ENGINES)
def test_guardrail_blocks_reschedule_after_three_failures(engine):
    # Order 4 has 3 failed attempts in the seed data.
    provider = Scripted(reschedule(order_id=4), escalate(4), LLMResponse(content="Escalated."))
    result = create_runner(engine, provider=provider, max_steps=6).resolve_incident(4)

    assert result.status == "ESCALATED"
    blocked = next(e for e in result.trace if e.tool_name == "reschedule_delivery")
    assert blocked.result["policy_blocked"] is True


@pytest.mark.parametrize("engine", ENGINES)
def test_escalation_ends_the_run(engine):
    provider = Scripted(escalate(1), reschedule())
    result = create_runner(engine, provider=provider, max_steps=6).resolve_incident(1)

    assert result.status == "ESCALATED"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("engine", ENGINES)
def test_provider_error_fails_without_messaging_the_customer(engine):
    class Broken(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            raise RuntimeError("Error code: 429 rate_limit_exceeded org_abc")

    result = create_runner(engine, provider=Broken(), max_steps=4).resolve_incident(1)
    assert result.status == "FAILED"
    assert result.notifications == []
    assert "org_" not in result.decision_summary


@pytest.mark.parametrize("engine", ENGINES)
def test_talk_only_run_is_not_resolved(engine):
    result = create_runner(engine, provider=Scripted(LLMResponse(content="All good.")), max_steps=4).resolve_incident(1)
    assert result.status == "FAILED"


@pytest.mark.parametrize("engine", ENGINES)
def test_endless_tool_calls_stop_at_the_step_limit(engine):
    class Loop(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            return get_order()

    result = create_runner(engine, provider=Loop(), max_steps=3).resolve_incident(1)
    assert result.status == "FAILED"


def test_agent_framework_sends_the_system_prompt_once():
    provider = Scripted(LLMResponse(content="Escalating to ops."))
    create_runner("agent_framework", provider=provider, max_steps=3).resolve_incident(1)
    first = provider.calls[0]
    assert [m["role"] for m in first].count("system") == 1
    assert "RescueFlow AI" in first[0]["content"]


def test_courier_hours_guardrail():
    # Courier 1 (order 1's courier) works 08:00-18:00.
    assert policy_violation("reschedule_delivery", {"order_id": 1, "start_time": "09:00", "end_time": "12:00"}, 1) is None
    blocked = policy_violation("reschedule_delivery", {"order_id": 1, "start_time": "17:00", "end_time": "20:00"}, 1)
    assert blocked and "courier availability" in blocked
