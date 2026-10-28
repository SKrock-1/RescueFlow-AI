"""
RescueFlow AI — Order Tools.

Read-only tool for retrieving order + delivery information.
"""

from __future__ import annotations

import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import Order, Delivery
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def get_order(order_id: int) -> dict[str, Any]:
    """Retrieve order details including delivery status for a given order ID.

    order_id: The numeric ID of the order to look up.
    """
    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return {"success": False, "error": f"Order {order_id} not found"}

        data: dict[str, Any] = {
            "success": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "customer_id": order.customer_id,
            "warehouse_id": order.warehouse_id,
            "package_size": order.package_size,
            "priority": order.priority,
            "status": order.status,
            "expected_delivery_date": str(order.expected_delivery_date) if order.expected_delivery_date else None,
        }

        # Attach delivery info if exists
        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        if delivery:
            data.update({
                "delivery_status": delivery.status,
                "delivery_courier_id": delivery.courier_id,
                "delivery_scheduled_date": str(delivery.scheduled_date) if delivery.scheduled_date else None,
                "delivery_scheduled_start": str(delivery.scheduled_start) if delivery.scheduled_start else None,
                "delivery_scheduled_end": str(delivery.scheduled_end) if delivery.scheduled_end else None,
                "delivery_attempt_count": delivery.attempt_count,
            })

        logger.info("Retrieved order %s (status=%s)", order.order_number, order.status)
        return data


# Register
registry.register(get_order, mutation=False)
