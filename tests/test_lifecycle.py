"""
RescueFlow AI — Lifecycle tests.

One test group per state machine that used to be implicit: incidents,
approvals, the escalate tool, deliveries and the derived order status,
the failed-attempt counter, stale runs, the agent's own run state,
webhook retries and the Shopify state tags.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agent.agent import AgentRunner
from app.agent.state import AgentState, AgentStatus
from app.database.engine import get_db
from app.database.models import AgentRun, Delivery, DeliveryAttempt, Incident, Order
from app.domain.lifecycle import (
    IllegalTransition,
    IncidentStatus,
    claim_incident,
    fail_stale_runs,
    move_incident,
)
from app.providers.base import LLMProvider, LLMResponse
from app.services.shopify_service import ShopifyService
from app.tools.delivery_tools import reassign_courier, reschedule_delivery, update_delivery_status
from app.tools.incident_tools import escalate_incident


def _call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


class RescheduleProvider(LLMProvider):
    def __init__(self):
        self.step = 0

    def generate(self, messages, tools=None, **kwargs):
        self.step += 1
        if self.step == 1:
            return LLMResponse(content="Reschedule.", tool_calls=[_call("c1", "reschedule_delivery", {
                "order_id": 1, "date": "2026-12-01", "start_time": "09:00", "end_time": "12:00"})])
        return LLMResponse(content="Done.")


def _incident(incident_id):
    with get_db() as db:
        return db.query(Incident).filter(Incident.id == incident_id).first()


# ── Incident lifecycle ──────────────────────────────────────────
def test_incident_illegal_move_raises():
    with get_db() as db:
        inc = db.query(Incident).filter(Incident.id == 1).first()
        with pytest.raises(IllegalTransition):
            move_incident(inc, IncidentStatus.EXECUTING)  # OPEN cannot jump to EXECUTING


def test_incident_claim_succeeds_only_once():
    with get_db() as db:
        assert claim_incident(db, 1, IncidentStatus.OPEN, IncidentStatus.RUNNING) is True
    with get_db() as db:
        assert claim_incident(db, 1, IncidentStatus.OPEN, IncidentStatus.RUNNING) is False


def test_finished_incident_cannot_run_again():
    runner = AgentRunner(provider=RescheduleProvider(), max_steps=4)
    assert runner.resolve_incident(1).status == "RESOLVED"
    with pytest.raises(IllegalTransition):
        AgentRunner(provider=RescheduleProvider(), max_steps=4).resolve_incident(1)


# ── Approval gate ───────────────────────────────────────────────
def test_approval_runs_at_most_once():
    runner = AgentRunner(provider=RescheduleProvider(), max_steps=4)
    runner.resolve_incident(1, plan_only=True)
    assert runner.execute_approved(1).status == "RESOLVED"
    with pytest.raises(ValueError):
        runner.execute_approved(1)  # second click / second tab
    with pytest.raises(ValueError):
        runner.reject_proposal(1)  # cannot reject what already ran
    with get_db() as db:
        approvals = db.query(AgentRun).filter(AgentRun.incident_id == 1, AgentRun.action_type == "approval").count()
    assert approvals == 1


def test_superseded_plan_cannot_be_approved():
    runner = AgentRunner(provider=RescheduleProvider(), max_steps=4)
    runner.resolve_incident(1, plan_only=True)
    assert AgentRunner.supersede_open_incidents(order_id=1) == 1
    assert _incident(1).status == "SUPERSEDED"
    with pytest.raises(ValueError):
        runner.execute_approved(1)


# ── Escalate tool ───────────────────────────────────────────────
def test_escalation_never_reopens_a_finished_incident():
    with get_db() as db:
        db.query(Incident).filter(Incident.id == 1).update({Incident.status: "RESOLVED"})
    result = escalate_incident(order_id=1, reason="Customer asked for a call.")
    assert result["success"] is True
    assert result["incident_id"] != 1
    assert _incident(1).status == "RESOLVED"


def test_escalation_moves_the_active_incident():
    result = escalate_incident(order_id=1, reason="No slots.")
    assert result["incident_id"] == 1
    assert _incident(1).status == "ESCALATED"


# ── Delivery lifecycle and derived order status ─────────────────
def _delivered_order_id():
    with get_db() as db:
        return db.query(Delivery).filter(Delivery.status == "DELIVERED").first().order_id


def test_delivered_parcel_cannot_be_rescheduled_or_changed():
    order_id = _delivered_order_id()
    assert reschedule_delivery(order_id, "2026-12-01", "09:00", "12:00")["success"] is False
    assert update_delivery_status(order_id, "IN_TRANSIT")["success"] is False
    assert reassign_courier(order_id, 2)["success"] is False
    assert escalate_incident(order_id, "test")["success"] is False


def test_order_status_follows_delivery_status():
    update_delivery_status(1, "ON_HOLD")
    with get_db() as db:
        assert db.query(Order).filter(Order.id == 1).first().status == "ON_HOLD"
    reschedule_delivery(1, "2026-12-01", "09:00", "12:00")
    with get_db() as db:
        assert db.query(Delivery).filter(Delivery.order_id == 1).first().status == "RESCHEDULED"
        assert db.query(Order).filter(Order.id == 1).first().status == "IN_TRANSIT"


def test_reassigning_keeps_the_rescheduled_window():
    reschedule_delivery(1, "2026-12-01", "09:00", "12:00")
    result = reassign_courier(1, 2)
    assert result["success"] is True
    assert result["status"] == "RESCHEDULED"


# ── Failed-attempt counter and sync ─────────────────────────────
FAKE_ORDER = {
    "id": 990001,
    "name": "#9901",
    "customer": {"first_name": "Test", "last_name": "Buyer", "phone": "+910000000001", "email": "t@example.com"},
    "shipping_address": {"address1": "1 Test Road", "city": "Bengaluru", "phone": "+910000000001"},
    "tags": "",
    "note": "",
    "line_items": [],
}


def _attempts(order_id):
    with get_db() as db:
        deliv = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        rows = db.query(DeliveryAttempt).filter(DeliveryAttempt.delivery_id == deliv.id).count()
        return deliv.attempt_count, rows


def test_only_new_ndrs_count_failed_attempts():
    svc = ShopifyService(store_url="example.myshopify.com", access_token="x")
    order_id, _ = svc.sync_shopify_order_to_db(FAKE_ORDER)
    assert _attempts(order_id) == (1, 1)
    svc.sync_shopify_order_to_db(FAKE_ORDER)  # console refresh / plan again
    assert _attempts(order_id) == (1, 1)
    svc.sync_shopify_order_to_db(FAKE_ORDER, failure_reason="Gate locked", new_failure=True)
    assert _attempts(order_id) == (2, 2)


def test_customer_reply_reaches_the_incident():
    svc = ShopifyService(store_url="example.myshopify.com", access_token="x")
    _, inc_id = svc.sync_shopify_order_to_db(FAKE_ORDER, context_note='Customer replied: "after 3pm please"')
    assert "after 3pm please" in _incident(inc_id).description


def test_stale_running_incident_is_released():
    with get_db() as db:
        db.query(Incident).filter(Incident.id == 1).update({Incident.status: "RUNNING"})
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    with get_db() as db:
        assert fail_stale_runs(db, order_id=1, now=later) == 1
    assert _incident(1).status == "FAILED"


# ── Agent run state ─────────────────────────────────────────────
def test_agent_run_cannot_change_outcome_after_finishing():
    state = AgentState(incident_id=1, order_id=1, customer_id=1, goal="g")
    state.finish(AgentStatus.RESOLVED)
    state.finish(AgentStatus.RESOLVED)  # same outcome is a no-op
    with pytest.raises(ValueError):
        state.finish(AgentStatus.ESCALATED)


def test_escalation_ends_the_autonomous_run():
    class EscalateThenAct(LLMProvider):
        def __init__(self):
            self.step = 0

        def generate(self, messages, tools=None, **kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(content="Escalating.", tool_calls=[_call("e", "escalate_incident", {"order_id": 1, "reason": "x"})])
            return LLMResponse(content="Rescheduling anyway.", tool_calls=[_call("r", "reschedule_delivery", {
                "order_id": 1, "date": "2026-12-01", "start_time": "09:00", "end_time": "12:00"})])

    provider = EscalateThenAct()
    result = AgentRunner(provider=provider, max_steps=5).resolve_incident(1)
    assert result.status == "ESCALATED"
    assert provider.step == 1  # no further actions after the hand-off


# ── Webhook retries ─────────────────────────────────────────────
def test_repeated_webhook_event_is_ignored():
    from app.server import _first_time

    assert _first_time("evt-123", "delivery_failed") is True
    assert _first_time("evt-123", "delivery_failed") is False
    assert _first_time(None, "delivery_failed") is True


# ── Shopify state tags ──────────────────────────────────────────
def test_shopify_tags_are_replaced_not_stacked(monkeypatch):
    svc = ShopifyService(store_url="example.myshopify.com", access_token="x")
    existing = "vip-repeat-buyer, rescueflow-rescued, rf-update_delivery_status, rf-reschedule_delivery"
    monkeypatch.setattr(svc, "get_order", lambda oid: {"order": {"tags": existing, "note": ""}})
    sent = {}
    monkeypatch.setattr(svc, "_request", lambda path, method="GET", data=None: sent.update(data or {}) or {"ok": True})

    svc.update_order_rescue_status(1, "escalate_incident", "Escalated.", state_tag="rescueflow-escalated")
    tags = {t.strip() for t in sent["order"]["tags"].split(",")}
    assert tags == {"vip-repeat-buyer", "rescueflow-escalated", "rf-escalate_incident"}
