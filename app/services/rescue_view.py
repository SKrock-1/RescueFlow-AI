"""
RescueFlow AI — Read model for the operations console.

Everything the console shows about a rescue comes from here, and everything
here is read from stored records (incidents, agent steps, deliveries). The
console never infers success from Shopify tags or from the agent's own words.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime
import json
from typing import Any

from app.database.engine import get_db
from app.database.models import AgentRun, Courier, Customer, Delivery, Incident, Order
from app.services.notifications import NotificationDispatcher
from app.services.policy import PolicyEngine
from app.services.shopify_service import OUTCOME_STATE_TAGS

# Incident status -> (label shown to operators, badge colour). Colour is never the only signal.
STATE_META: dict[str | None, tuple[str, str]] = {
    None: ("Not planned", "orange"),
    "OPEN": ("Not planned", "orange"),
    "AWAITING_APPROVAL": ("Awaiting approval", "blue"),
    "RESOLVED": ("Rescued, verified", "green"),
    "ESCALATED": ("Escalated to ops", "gray"),
    "FAILED": ("Failed", "red"),
    "REJECTED": ("Plan rejected", "gray"),
}

HIDDEN_STATES = {"SUPERSEDED"}

TOOL_LABELS = {
    "reschedule_delivery": "Reschedule delivery",
    "reassign_courier": "Reassign courier",
    "update_delivery_status": "Change delivery status",
    "escalate_incident": "Escalate to human operations",
}


def state_label(status: str | None) -> tuple[str, str]:
    return STATE_META.get(status, (str(status).replace("_", " ").title(), "gray"))


def local_order_number(shopify_order: dict[str, Any]) -> str:
    name = str(shopify_order.get("name") or shopify_order.get("id") or "")
    return f"SHP-{name.replace('#', '').strip()}"


def latest_incident(local_number: str) -> dict[str, Any] | None:
    """Latest visible incident for a local order number, or None if never planned."""
    with get_db() as db:
        order = db.query(Order).filter(Order.order_number == local_number).first()
        if not order:
            return None
        inc = (
            db.query(Incident)
            .filter(Incident.order_id == order.id, Incident.status.notin_(HIDDEN_STATES))
            .order_by(Incident.id.desc())
            .first()
        )
        if not inc:
            return None
        return {
            "id": inc.id,
            "order_id": order.id,
            "status": inc.status,
            "decision": inc.agent_decision or "",
        }


def describe_proposal(tool_name: str, args: dict[str, Any]) -> str:
    """One plain sentence describing a proposed change."""
    if tool_name == "reschedule_delivery":
        return f"Reschedule delivery to {args.get('date')}, {args.get('start_time')} to {args.get('end_time')}."
    if tool_name == "reassign_courier":
        with get_db() as db:
            courier = db.query(Courier).filter(Courier.id == args.get("courier_id")).first()
            who = f"{courier.name} ({courier.vehicle_type})" if courier else f"courier #{args.get('courier_id')}"
        return f"Reassign the delivery to {who}."
    if tool_name == "update_delivery_status":
        return f"Change the delivery status to {str(args.get('status', '')).upper()}."
    if tool_name == "escalate_incident":
        return "Escalate to human operations."
    return f"Run {tool_name}."


@dataclass
class Check:
    label: str
    passed: bool
    detail: str
    blocking: bool = True


def _time_block(t) -> str:
    if t.hour < 12:
        return "morning"
    if t.hour < 16:
        return "afternoon"
    return "evening"


def _parse_time(value: Any):
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt).time()
        except ValueError:
            continue
    return None


def proposal_checks(order_id: int, tool_name: str, args: dict[str, Any], today: date_cls | None = None) -> list[Check]:
    """Policy checks shown on the approval card. Blocking failures disable Approve."""
    today = today or date_cls.today()
    checks: list[Check] = []
    with get_db() as db:
        deliv = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        order = db.query(Order).filter(Order.id == order_id).first()
        customer = db.query(Customer).filter(Customer.id == order.customer_id).first() if order else None

        if tool_name == "reschedule_delivery":
            attempts = deliv.attempt_count if deliv else 0
            res = PolicyEngine.rule_repeated_failure_escalation(attempts)
            checks.append(Check("Failed attempts below limit", res.passed, f"{attempts} failed attempt(s); the limit is 3."))

            start, end = _parse_time(args.get("start_time")), _parse_time(args.get("end_time"))
            courier = db.query(Courier).filter(Courier.id == deliv.courier_id).first() if deliv and deliv.courier_id else None
            if start and end and courier and courier.available_from and courier.available_until:
                res = PolicyEngine.rule_courier_hours(start, end, courier.available_from, courier.available_until)
                checks.append(Check(
                    "Within courier hours", res.passed,
                    f"{courier.name} works {courier.available_from:%H:%M} to {courier.available_until:%H:%M}.",
                ))
            if start and customer and customer.preferred_delivery_time:
                block = _time_block(start)
                ok = block == customer.preferred_delivery_time.lower()
                checks.append(Check(
                    "Matches customer's preferred window", ok,
                    f"Customer prefers {customer.preferred_delivery_time}; proposed window is {block}.",
                    blocking=False,
                ))
            try:
                proposed_date = datetime.strptime(str(args.get("date")), "%Y-%m-%d").date()
                checks.append(Check(
                    "Date is today or later", proposed_date >= today,
                    f"Proposed {proposed_date}; today is {today}.", blocking=False,
                ))
            except ValueError:
                checks.append(Check("Valid date", False, f"'{args.get('date')}' is not a YYYY-MM-DD date."))

        elif tool_name == "reassign_courier":
            courier = db.query(Courier).filter(Courier.id == args.get("courier_id")).first()
            if courier:
                res = PolicyEngine.rule_courier_active(courier.status)
                checks.append(Check("Courier is active", res.passed, f"{courier.name} is {courier.status}."))
            else:
                checks.append(Check("Courier exists", False, f"No courier #{args.get('courier_id')}."))

        elif tool_name == "escalate_incident":
            checks.append(Check("Escalation is always allowed", True, "Hands the order to a person.", blocking=False))
    return checks


def message_preview(order_id: int, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """The exact customer message an approval would send, or why none will be sent."""
    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        customer = db.query(Customer).filter(Customer.id == order.customer_id).first() if order else None
        name = customer.name if customer else "Customer"
        phone = (customer.phone if customer else "") or ""
        order_number = order.order_number if order else ""

    if tool_name == "reschedule_delivery":
        channel = "WhatsApp"
        text = NotificationDispatcher.build_rescheduled_message(
            name, order_number, str(args.get("date")), str(args.get("start_time")), str(args.get("end_time"))
        )
    elif tool_name == "escalate_incident":
        channel = "SMS"
        text = NotificationDispatcher.build_escalated_message(order_number, phone or "your number")
    else:
        return {"channel": None, "recipient": name, "phone": phone, "text": None,
                "note": "This action does not message the customer."}

    if not phone.strip():
        return {"channel": channel, "recipient": name, "phone": "", "text": None,
                "note": f"No phone number on file for {name}, so no message will be sent."}
    return {"channel": channel, "recipient": name, "phone": phone, "text": text, "note": None}


def shopify_preview(tool_name: str) -> dict[str, Any]:
    """Tags and note that approval would write to the Shopify order if it succeeds."""
    outcome = "ESCALATED" if tool_name == "escalate_incident" else "RESOLVED"
    return {
        "tags": [OUTCOME_STATE_TAGS[outcome], f"rf-{tool_name}", "autonomous-resolution"],
        "note": "[RescueFlow AI] followed by the verified outcome.",
    }


def last_notification(incident_id: int) -> dict[str, Any] | None:
    """The customer message actually recorded for an incident, if one was sent."""
    with get_db() as db:
        run = (
            db.query(AgentRun)
            .filter(AgentRun.incident_id == incident_id, AgentRun.action_type == "notification")
            .order_by(AgentRun.id.desc())
            .first()
        )
        if not run or not run.result:
            return None
        data = json.loads(run.result)
        if data.get("status") != "SENT":
            return {"sent": False, "reason": run.decision or "Not sent."}
        return {
            "sent": True,
            "channel": data.get("channel", ""),
            "recipient": data.get("recipient", ""),
            "contact": data.get("contact", ""),
            "message": data.get("message", ""),
            "timestamp": run.timestamp,
        }


def queue_counts(local_numbers: list[str]) -> dict[str, int]:
    """Counts by state for the orders currently listed."""
    counts = {"listed": len(local_numbers), "awaiting": 0, "rescued": 0, "attention": 0}
    for num in local_numbers:
        inc = latest_incident(num)
        status = inc["status"] if inc else None
        if status == "AWAITING_APPROVAL":
            counts["awaiting"] += 1
        elif status == "RESOLVED":
            counts["rescued"] += 1
        elif status in {"FAILED", "ESCALATED"}:
            counts["attention"] += 1
    return counts
