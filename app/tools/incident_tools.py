"""
RescueFlow AI — Incident Tools.

Mutation tool for escalating incidents when automated resolution is infeasible.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import Incident, Order, Delivery
from app.domain.lifecycle import (
    ORDER_STATUS_FOR_DELIVERY,
    DeliveryStatus,
    IncidentStatus,
    delivery_problem,
    move_delivery,
    move_incident,
)
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def escalate_incident(order_id: int, reason: str) -> dict[str, Any]:
    """Escalate a delivery incident to human logistics support when recovery is not feasible.

    order_id: The numeric ID of the order being escalated.
    reason: Detailed explanation of why automated resolution failed and human intervention is needed.
    """
    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return {
                "success": False,
                "error": "Order not found",
                "reason": f"Order {order_id} does not exist.",
            }

        # Escalate the incident that is being worked on now. A finished or
        # superseded incident is history and must never be reopened here.
        incident = (
            db.query(Incident)
            .filter(
                Incident.order_id == order_id,
                Incident.status.in_([IncidentStatus.OPEN.value, IncidentStatus.RUNNING.value,
                                     IncidentStatus.EXECUTING.value]),
            )
            .order_by(Incident.id.desc())
            .first()
        )

        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        problem = delivery_problem(delivery, DeliveryStatus.ESCALATED)
        if problem:
            return {
                "success": False,
                "error": "Escalation not allowed",
                "reason": problem,
            }

        if not incident:
            incident = Incident(
                order_id=order_id,
                incident_type="escalation",
                severity="high",
                description=f"Auto-created escalation incident: {reason}",
                status=IncidentStatus.ESCALATED.value,
                agent_decision=reason,
                resolved_at=datetime.now(timezone.utc),
            )
            db.add(incident)
        else:
            move_incident(incident, IncidentStatus.ESCALATED)
            incident.agent_decision = reason

        if delivery:
            move_delivery(delivery, order, DeliveryStatus.ESCALATED)
        else:
            order.status = ORDER_STATUS_FOR_DELIVERY[DeliveryStatus.ESCALATED]

        db.flush()

        logger.warning("Escalated incident for order %d: %s", order_id, reason)
        return {
            "success": True,
            "order_id": order_id,
            "incident_id": incident.id,
            "status": "ESCALATED",
            "escalation_reason": reason,
            "message": f"Order {order_id} has been escalated to senior human operations.",
        }


# Register
registry.register(escalate_incident, mutation=True)
