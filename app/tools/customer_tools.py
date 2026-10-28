"""
RescueFlow AI — Customer Tools.

Read-only tool for retrieving customer profile and preferences.
"""

from __future__ import annotations

import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import Customer, AgentMemory
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def get_customer_profile(customer_id: int) -> dict[str, Any]:
    """Retrieve customer profile, contact preferences, and special instructions.

    customer_id: The numeric ID of the customer to look up.
    """
    with get_db() as db:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return {"success": False, "error": f"Customer {customer_id} not found"}

        memories = (
            db.query(AgentMemory)
            .filter(AgentMemory.customer_id == customer_id)
            .order_by(AgentMemory.importance.desc())
            .all()
        )

        memory_items = [
            {
                "memory_type": m.memory_type,
                "content": m.content,
                "importance": m.importance,
            }
            for m in memories
        ]

        # Analyze profile traits
        is_vip = any("vip" in (m.content or "").lower() for m in memories)
        is_commercial = any("commercial" in (m.content or "").lower() or "office" in (m.content or "").lower() for m in memories)

        data: dict[str, Any] = {
            "success": True,
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "address": customer.address,
            "preferred_delivery_time": customer.preferred_delivery_time,
            "preferred_contact_method": customer.preferred_contact_method,
            "special_instructions": customer.special_instructions,
            "is_vip": is_vip,
            "address_type": "commercial" if is_commercial else "residential",
            "memories": memory_items,
        }

        logger.info("Retrieved customer profile %s (%s)", customer.name, customer.preferred_delivery_time)
        return data


# Register
registry.register(get_customer_profile, mutation=False)
