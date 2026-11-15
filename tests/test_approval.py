"""
RescueFlow AI — Human approval gate and honest-status tests.

Covers plan-only runs, approving or rejecting a proposal, verification of
executed changes, and provider failures being reported as FAILED.
"""

from __future__ import annotations

import pytest

from app.agent.agent import AgentRunner, describe_provider_error
from app.database.engine import get_db
from app.database.models import AgentRun, Delivery, Incident
from app.database.seed import seed_all
from app.providers.base import LLMProvider, LLMResponse


@pytest.fixture()
def fresh_db():
    seed_all()
    yield


def _call(call_id: str, name: str, args: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


class RescheduleProvider(LLMProvider):
    """Investigates order 1, then asks to reschedule it."""

    def __init__(self, order_id_in_call: int = 1) -> None:
        self.step = 0
        self.order_id_in_call = order_id_in_call

    def generate(self, messages, tools=None, **kwargs):
        self.step += 1
        if self.step == 1:
            return LLMResponse(content="Inspecting order.", tool_calls=[_call("c1", "get_order", {"order_id": 1})])
        if self.step == 2:
            return LLMResponse(
                content="Reschedule to the customer's morning window.",
                tool_calls=[_call("c2", "reschedule_delivery", {
                    "order_id": self.order_id_in_call, "date": "2026-09-14",
                    "start_time": "09:00", "end_time": "12:00",
                })],
            )
        return LLMResponse(content="Rescheduled to 2026-09-14 09:00-12:00.")


def _delivery_date(order_id: int):
    with get_db() as db:
        deliv = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        return deliv.scheduled_date, deliv.status


def test_plan_only_stops_before_mutation(fresh_db):
    before = _delivery_date(1)
    runner = AgentRunner(provider=RescheduleProvider(), max_steps=6)
    result = runner.resolve_incident(1, plan_only=True)

    assert result.status == "AWAITING_APPROVAL"
    assert result.action_taken is None
    assert result.proposed_action["tool_name"] == "reschedule_delivery"
    assert result.notifications == []
    # Nothing in the database changed yet
    assert _delivery_date(1) == before

    proposal = AgentRunner.get_pending_proposal(1)
    assert proposal is not None
    assert proposal["arguments"]["date"] == "2026-09-14"


def test_proposal_is_pinned_to_the_incident_order(fresh_db):
    runner = AgentRunner(provider=RescheduleProvider(order_id_in_call=2), max_steps=6)
    result = runner.resolve_incident(1, plan_only=True)
    assert result.proposed_action["arguments"]["order_id"] == 1


def test_approve_executes_and_verifies(fresh_db):
    runner = AgentRunner(provider=RescheduleProvider(), max_steps=6)
    runner.resolve_incident(1, plan_only=True)

    result = runner.execute_approved(1)

    assert result.status == "RESOLVED"
    assert result.action_taken == "reschedule_delivery"
    scheduled, status = _delivery_date(1)
    assert str(scheduled) == "2026-09-14"
    assert status == "RESCHEDULED"
    with get_db() as db:
        kinds = [r.action_type for r in db.query(AgentRun).filter(AgentRun.incident_id == 1).all()]
    assert "approval" in kinds
    assert "verification" in kinds
    assert AgentRunner.get_pending_proposal(1) is None


def test_reject_leaves_data_untouched(fresh_db):
    before = _delivery_date(1)
    runner = AgentRunner(provider=RescheduleProvider(), max_steps=6)
    runner.resolve_incident(1, plan_only=True)

    result = runner.reject_proposal(1, "Customer asked for an evening slot.")

    assert result.status == "REJECTED"
    assert _delivery_date(1) == before
    with get_db() as db:
        assert db.query(Incident).filter(Incident.id == 1).first().status == "REJECTED"
    with pytest.raises(ValueError):
        runner.execute_approved(1)


def test_provider_error_is_failed_not_escalated(fresh_db):
    class RateLimitedProvider(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            raise RuntimeError("Error code: 429 - rate_limit_exceeded for org_01abc123 on tokens per day")

    result = AgentRunner(provider=RateLimitedProvider(), max_steps=3).resolve_incident(1)

    assert result.status == "FAILED"
    assert result.notifications == []
    assert "org_" not in result.decision_summary
    assert "rate-limited" in result.decision_summary


def test_no_action_is_not_reported_as_resolved(fresh_db):
    class TalkOnlyProvider(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            return LLMResponse(content="Everything looks fine to me.")

    result = AgentRunner(provider=TalkOnlyProvider(), max_steps=3).resolve_incident(1)
    assert result.status == "FAILED"
    assert "without taking a recovery action" in result.decision_summary


def test_describe_provider_error_hides_details():
    assert describe_provider_error(Exception("429 org_123")) == "The AI provider rate-limited the request (429)."
    assert "org_" not in describe_provider_error(Exception("boom org_123"))
