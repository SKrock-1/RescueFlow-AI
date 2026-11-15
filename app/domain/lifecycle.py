"""
RescueFlow AI — Explicit lifecycles for incidents, deliveries and orders.

Every status column used to be a free-form string written from several
files, so any code path could move a record into any state (a delivered
parcel could be rescheduled, a resolved incident could be re-escalated, an
approval could run twice). This module is now the single place that names
the states and the moves allowed between them. All status writes go through
the helpers below.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import AgentRun, Delivery, DeliveryAttempt, Incident, Order


class IllegalTransition(ValueError):
    """Raised when code tries to move a record into a state it cannot reach."""


# ──────────────────────────────────────────
# Incident lifecycle
# ──────────────────────────────────────────
class IncidentStatus(str, Enum):
    OPEN = "OPEN"                            # created, nobody working on it
    RUNNING = "RUNNING"                      # an agent run has claimed it
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # plan stored, waiting for a person
    EXECUTING = "EXECUTING"                  # approved change is being applied
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"                # replaced by a newer plan


_I = IncidentStatus
INCIDENT_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    _I.OPEN: {_I.RUNNING, _I.ESCALATED, _I.FAILED, _I.SUPERSEDED},
    _I.RUNNING: {_I.AWAITING_APPROVAL, _I.RESOLVED, _I.ESCALATED, _I.FAILED},
    _I.AWAITING_APPROVAL: {_I.EXECUTING, _I.REJECTED, _I.SUPERSEDED},
    _I.EXECUTING: {_I.RESOLVED, _I.ESCALATED, _I.FAILED},
    _I.RESOLVED: set(),
    _I.ESCALATED: set(),
    _I.FAILED: set(),
    _I.REJECTED: set(),
    _I.SUPERSEDED: set(),
}

# Incidents in these states are being worked on for their order.
ACTIVE_INCIDENT_STATES = {_I.OPEN, _I.RUNNING, _I.AWAITING_APPROVAL, _I.EXECUTING}
TERMINAL_INCIDENT_STATES = {s for s, nxt in INCIDENT_TRANSITIONS.items() if not nxt}
STALE_RUN_AFTER = timedelta(minutes=10)


def _check(kind: str, table: dict, current: str, new: Enum) -> None:
    try:
        cur = type(new)(current)
    except ValueError as exc:
        raise IllegalTransition(f"{kind} has unknown status '{current}'.") from exc
    if cur == new:
        return
    if new not in table[cur]:
        raise IllegalTransition(f"{kind} cannot move from {cur.value} to {new.value}.")


def can_incident_move(current: str, new: IncidentStatus) -> bool:
    try:
        _check("Incident", INCIDENT_TRANSITIONS, current, new)
        return True
    except IllegalTransition:
        return False


def move_incident(incident: Incident, new: IncidentStatus) -> None:
    """Validated in-session status change for an incident."""
    _check(f"Incident #{incident.id}", INCIDENT_TRANSITIONS, incident.status, new)
    incident.status = new.value
    if new in {_I.RESOLVED, _I.ESCALATED}:
        incident.resolved_at = datetime.now(timezone.utc)


def claim_incident(db: Session, incident_id: int, expected: IncidentStatus, new: IncidentStatus) -> bool:
    """Atomically move an incident from ``expected`` to ``new``.

    Returns False when another caller got there first (double click, two
    webhooks, two browser tabs), so the work runs at most once.
    """
    if new not in INCIDENT_TRANSITIONS[expected]:
        raise IllegalTransition(f"Incident cannot move from {expected.value} to {new.value}.")
    updated = (
        db.query(Incident)
        .filter(Incident.id == incident_id, Incident.status == expected.value)
        .update({Incident.status: new.value}, synchronize_session=False)
    )
    return updated == 1


def fail_stale_runs(db: Session, order_id: int, now: datetime | None = None) -> int:
    """Mark RUNNING/EXECUTING incidents with no activity for 10 minutes as FAILED.

    A crashed process would otherwise leave the incident claimed forever.
    """
    now = now or datetime.now(timezone.utc)
    count = 0
    stuck = (
        db.query(Incident)
        .filter(Incident.order_id == order_id, Incident.status.in_([_I.RUNNING.value, _I.EXECUTING.value]))
        .all()
    )
    for inc in stuck:
        last = db.query(func.max(AgentRun.timestamp)).filter(AgentRun.incident_id == inc.id).scalar()
        last = last or inc.created_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or now - last > STALE_RUN_AFTER:
            move_incident(inc, _I.FAILED)
            inc.agent_decision = "The run was interrupted before it finished. Nothing further was changed; plan again."
            count += 1
    return count


# ──────────────────────────────────────────
# Delivery lifecycle
# ──────────────────────────────────────────
class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    FAILED = "FAILED"
    RESCHEDULED = "RESCHEDULED"
    ON_HOLD = "ON_HOLD"
    ESCALATED = "ESCALATED"
    DELIVERED = "DELIVERED"
    REASSIGNED = "REASSIGNED"  # legacy value written by older versions; treated like SCHEDULED


_D = DeliveryStatus
_ACTIVE_NEXT = {_D.IN_TRANSIT, _D.RESCHEDULED, _D.FAILED, _D.ON_HOLD, _D.ESCALATED, _D.DELIVERED}
DELIVERY_TRANSITIONS: dict[DeliveryStatus, set[DeliveryStatus]] = {
    _D.SCHEDULED: _ACTIVE_NEXT,
    _D.REASSIGNED: _ACTIVE_NEXT | {_D.SCHEDULED},
    _D.IN_TRANSIT: {_D.DELIVERED, _D.FAILED, _D.RESCHEDULED, _D.ON_HOLD, _D.ESCALATED},
    _D.RESCHEDULED: _ACTIVE_NEXT,
    _D.FAILED: {_D.RESCHEDULED, _D.SCHEDULED, _D.IN_TRANSIT, _D.ON_HOLD, _D.ESCALATED},
    _D.ON_HOLD: {_D.SCHEDULED, _D.RESCHEDULED, _D.IN_TRANSIT, _D.ESCALATED},
    _D.ESCALATED: {_D.SCHEDULED, _D.RESCHEDULED, _D.ON_HOLD, _D.DELIVERED},
    _D.DELIVERED: set(),
}

# The order's status is derived from its delivery, never written separately.
ORDER_STATUS_FOR_DELIVERY: dict[DeliveryStatus, str] = {
    _D.SCHEDULED: "IN_TRANSIT",
    _D.REASSIGNED: "IN_TRANSIT",
    _D.IN_TRANSIT: "IN_TRANSIT",
    _D.RESCHEDULED: "IN_TRANSIT",
    _D.FAILED: "FAILED",
    _D.ON_HOLD: "ON_HOLD",
    _D.ESCALATED: "ESCALATED",
    _D.DELIVERED: "DELIVERED",
}

SETTABLE_DELIVERY_STATUSES = {s.value for s in DeliveryStatus if s is not _D.REASSIGNED}


def delivery_problem(delivery: Delivery | None, new: DeliveryStatus) -> str | None:
    """Plain reason a delivery cannot move to ``new``, or None if it can."""
    if delivery is None:
        return None
    try:
        _check(f"Delivery for order {delivery.order_id}", DELIVERY_TRANSITIONS, delivery.status, new)
    except IllegalTransition as exc:
        return str(exc)
    return None


def move_delivery(delivery: Delivery, order: Order | None, new: DeliveryStatus) -> None:
    """Validated delivery status change; keeps the order's status in step."""
    _check(f"Delivery for order {delivery.order_id}", DELIVERY_TRANSITIONS, delivery.status, new)
    delivery.status = new.value
    if order is not None:
        order.status = ORDER_STATUS_FOR_DELIVERY[new]


def record_failed_attempt(
    db: Session,
    delivery: Delivery,
    order: Order | None,
    reason: str,
    location: str | None = None,
    notes: str | None = None,
) -> DeliveryAttempt | None:
    """Count one more failed attempt. Returns None for a delivered parcel."""
    if delivery.status == _D.DELIVERED.value:
        return None
    delivery.attempt_count = (delivery.attempt_count or 0) + 1
    move_delivery(delivery, order, _D.FAILED)
    attempt = DeliveryAttempt(
        delivery_id=delivery.id,
        attempt_number=delivery.attempt_count,
        reason=reason[:100] if reason else "unknown",
        location=location,
        notes=notes,
    )
    db.add(attempt)
    return attempt
