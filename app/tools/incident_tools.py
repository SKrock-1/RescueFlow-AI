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

        # Find active incident for this order or create one
        incident = (
            db.query(Incident)
            .filter(Incident.order_id == order_id)
            .order_by(Incident.id.desc())
            .first()
        )

        if not incident:
            incident = Incident(
                order_id=order_id,
                incident_type="escalation",
                severity="high",
                description=f"Auto-created escalation incident: {reason}",
                status="ESCALATED",
                agent_decision=reason,
                resolved_at=None,
            )
            db.add(incident)
        else:
            incident.status = "ESCALATED"
            incident.agent_decision = reason
            incident.resolved_at = datetime.now(timezone.utc)

        # Update order & delivery status
        order.status = "ESCALATED"
        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        if delivery:
            delivery.status = "ESCALATED"

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
