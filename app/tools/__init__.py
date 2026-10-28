"""
RescueFlow AI — Tools Package.

Importing this package automatically registers all tools with the global ToolRegistry.
"""

from app.tools.registry import registry, ToolRegistry
from app.tools.order_tools import get_order
from app.tools.customer_tools import get_customer_profile
from app.tools.courier_tools import get_courier_availability
from app.tools.delivery_tools import (
    get_delivery_history,
    find_available_delivery_slots,
    reschedule_delivery,
    reassign_courier,
    update_delivery_status,
)
from app.tools.incident_tools import escalate_incident

__all__ = [
    "registry",
    "ToolRegistry",
    "get_order",
    "get_customer_profile",
    "get_courier_availability",
    "get_delivery_history",
    "find_available_delivery_slots",
    "reschedule_delivery",
    "reassign_courier",
    "update_delivery_status",
    "escalate_incident",
]
