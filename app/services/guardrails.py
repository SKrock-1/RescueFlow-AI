"""
RescueFlow AI — Hard guardrails for data-changing tools.

The single check every engine (the hand-written loop and the Agent
Framework agent) runs before a mutation. It returns the reason a call is
blocked, or None. The same rules mark checks as blocking on the console's
approval card, so what the operator sees and what the agent is allowed to
do cannot drift apart.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database.engine import get_db
from app.database.models import Courier, Delivery
from app.services.policy import PolicyEngine


def _parse_time(value: Any):
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt).time()
        except ValueError:
            continue
    return None


def policy_violation(tool_name: str, arguments: dict[str, Any], default_order_id: int) -> str | None:
    """Return the guardrail message that blocks this mutation, or None if allowed."""
    if tool_name == "reschedule_delivery":
        target_order_id = arguments.get("order_id", default_order_id)
        with get_db() as db:
            deliv = db.query(Delivery).filter(Delivery.order_id == target_order_id).first()
            if not deliv:
                return None
            rule = PolicyEngine.rule_repeated_failure_escalation(deliv.attempt_count)
            if not rule.passed:
                return rule.message
            courier = (
                db.query(Courier).filter(Courier.id == deliv.courier_id).first() if deliv.courier_id else None
            )
            start, end = _parse_time(arguments.get("start_time")), _parse_time(arguments.get("end_time"))
            if courier and start and end and courier.available_from and courier.available_until:
                rule = PolicyEngine.rule_courier_hours(start, end, courier.available_from, courier.available_until)
                if not rule.passed:
                    return rule.message

    elif tool_name == "reassign_courier":
        target_courier_id = arguments.get("courier_id")
        if target_courier_id:
            with get_db() as db:
                courier = db.query(Courier).filter(Courier.id == target_courier_id).first()
                if courier:
                    rule = PolicyEngine.rule_courier_active(courier.status)
                    if not rule.passed:
                        return rule.message
    return None
