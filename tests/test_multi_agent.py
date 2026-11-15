"""
RescueFlow AI — Multi-agent workflow tests (Phase 2).

The workflow runs offline through RoleAwareMockProvider; individual roles
are swapped for scripted providers to force critic rejections, bad JSON,
provider errors and per-role model routing.
"""

from __future__ import annotations

import json

from app.agent.engines import create_runner, resolve_engine_name
from app.database.engine import get_db
from app.database.models import AgentRun, Delivery
from app.multi_agent import roles
from app.multi_agent.workflow import MultiAgentRescue
from app.providers.base import LLMProvider, LLMResponse
from app.providers.mock_provider import MockProvider


def _agents(result):
    return [e.tool_name for e in result.trace if e.event_type == "agent"]


class RoleOverride(LLMProvider):
    """Role-aware mock, except chosen roles answer with a custom function."""

    def __init__(self, **overrides):
        self.base = roles.RoleAwareMockProvider()
        self.overrides = overrides
        self.seen_roles: list[str] = []

    def generate(self, messages, tools=None, **kwargs):
        system = next(m["content"] for m in messages if m["role"] == "system")
        role = system.split("ROLE: ", 1)[1].split()[0]
        self.seen_roles.append(role)
        if role in self.overrides:
            return LLMResponse(content=self.overrides[role](roles._facts_from(messages)))
        return self.base.generate(messages, tools, **kwargs)


def _slot_not_in(window):
    """Planner override: always propose a slot outside the given window."""
    def answer(facts):
        slots = facts["logistics"]["candidate_slots"]
        slot = next(s for s in slots if s["time_block"] != window)
        return json.dumps({"tool_name": "reschedule_delivery",
                           "arguments": {"date": slot["date"], "start_time": slot["start_time"], "end_time": slot["end_time"]},
                           "rationale": "Earliest slot."})
    return answer


def test_default_engine_is_multi_agent():
    assert resolve_engine_name() == "multi_agent"


def test_plan_only_runs_every_specialist_then_stops_at_the_gate():
    result = MultiAgentRescue(provider=MockProvider()).resolve_incident(1, plan_only=True)

    assert result.status == "AWAITING_APPROVAL"
    assert result.proposed_action["tool_name"] == "reschedule_delivery"
    assert result.proposed_action["arguments"]["order_id"] == 1
    assert result.proposed_action["arguments"]["start_time"] == "09:00"  # customer 1 prefers mornings
    assert set(_agents(result)) >= {"triage", "context", "logistics", "knowledge", "planner", "critic", "gate"}
    with get_db() as db:
        assert db.query(Delivery).filter(Delivery.order_id == 1).first().status == "FAILED"


def test_autonomous_run_executes_verifies_and_notifies():
    result = create_runner("multi_agent", provider=MockProvider()).resolve_incident(2)

    assert result.status == "RESOLVED"
    assert result.action_taken == "reschedule_delivery"
    kinds = [e.event_type for e in result.trace]
    assert kinds.index("tool_call", kinds.index("agent")) < kinds.index("verification")
    assert result.notifications and result.notifications[0]["type"] == "rescheduled"


def test_three_failed_attempts_are_escalated():
    result = MultiAgentRescue(provider=MockProvider()).resolve_incident(4)
    assert result.status == "ESCALATED"
    assert result.action_taken == "escalate_incident"


def test_critic_rejections_loop_back_then_force_escalation():
    provider = RoleOverride(PLANNER=_slot_not_in("morning"))
    result = MultiAgentRescue(provider=provider).resolve_incident(1, plan_only=True)

    critic_notes = [e for e in result.trace if e.event_type == "agent" and e.tool_name == "critic"]
    assert len(critic_notes) == 3                     # reject, reject, approve escalation
    assert provider.seen_roles.count("PLANNER") == 2  # third plan is forced, not asked
    assert result.status == "AWAITING_APPROVAL"
    assert result.proposed_action["tool_name"] == "escalate_incident"
    assert "rejected 2 plans" in result.proposed_action["arguments"]["reason"]


def test_hard_policy_rule_rejects_without_asking_the_critic_model():
    calls = {"n": 0}

    def outside_hours(facts):
        calls["n"] += 1
        if calls["n"] == 1:  # courier 1 works 08:00-18:00
            return json.dumps({"tool_name": "reschedule_delivery",
                               "arguments": {"date": "2026-12-01", "start_time": "18:00", "end_time": "21:00"},
                               "rationale": "Late slot."})
        return roles.RoleAwareMockProvider().generate(
            [{"role": "system", "content": "ROLE: PLANNER"},
             {"role": "user", "content": roles.FACTS_MARKER + json.dumps(facts) + roles.TASK_MARKER}]).content

    provider = RoleOverride(PLANNER=outside_hours)
    result = MultiAgentRescue(provider=provider).resolve_incident(1, plan_only=True)

    first_review = next(e for e in result.trace if e.event_type == "agent" and e.tool_name == "critic")
    assert first_review.status == "error" and "courier" in first_review.summary.lower()
    assert provider.seen_roles.count("CRITIC") == 1   # only the second, valid plan reached the model critic
    assert result.proposed_action["arguments"]["start_time"] == "09:00"


def test_invalid_json_falls_back_to_the_role_rule():
    provider = RoleOverride(TRIAGE=lambda facts: "I think the customer was out.")
    result = MultiAgentRescue(provider=provider).resolve_incident(1, plan_only=True)

    triage = next(e for e in result.trace if e.tool_name == "triage")
    assert "built-in rule" in triage.summary
    assert result.status == "AWAITING_APPROVAL"


def test_per_role_model_routing():
    critic_model = RoleOverride()
    engine = MultiAgentRescue(provider=MockProvider(), role_providers={"critic": critic_model})
    engine.resolve_incident(1, plan_only=True)
    assert critic_model.seen_roles == ["CRITIC"]


def test_provider_error_fails_cleanly():
    class Broken(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            raise RuntimeError("429 rate_limit org_secret")

    result = MultiAgentRescue(provider=Broken()).resolve_incident(1)
    assert result.status == "FAILED"
    assert result.notifications == []
    assert "org_" not in result.decision_summary
    with get_db() as db:
        assert db.query(Delivery).filter(Delivery.order_id == 1).first().status == "FAILED"


def test_trace_is_stored_for_the_console():
    result = MultiAgentRescue(provider=MockProvider()).resolve_incident(1, plan_only=True)
    with get_db() as db:
        stored = db.query(AgentRun).filter(AgentRun.incident_id == 1, AgentRun.action_type == "agent").count()
    assert stored == len([e for e in result.trace if e.event_type == "agent"])
