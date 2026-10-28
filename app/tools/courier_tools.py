"""
RescueFlow AI — Courier Tools.

Read-only tool for inspecting courier availability within a service area and date.
"""

from __future__ import annotations

import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import Courier
from app.tools.registry import registry

logger = logging.getLogger(__name__)


def get_courier_availability(area: str, date: str) -> dict[str, Any]:
    """Retrieve active couriers operating in a specific service area.

    area: The service area or city name (e.g. 'Bengaluru', 'Mumbai', 'Kolkata', 'Hyderabad', 'Delhi').
    date: The target date for courier assignment (format YYYY-MM-DD).
    """
    with get_db() as db:
        couriers = (
            db.query(Courier)
            .filter(
                Courier.service_area.ilike(f"%{area}%"),
                Courier.status == "active",
            )
            .all()
        )

        courier_list = [
            {
                "courier_id": c.id,
                "name": c.name,
                "vehicle_type": c.vehicle_type,
                "status": c.status,
                "service_area": c.service_area,
                "current_location": c.current_location,
                "available_from": str(c.available_from) if c.available_from else None,
                "available_until": str(c.available_until) if c.available_until else None,
            }
            for c in couriers
        ]

        logger.info("Found %d active couriers for area '%s' on %s", len(courier_list), area, date)
        return {
            "success": True,
            "area": area,
            "date": date,
            "available_couriers_count": len(courier_list),
            "couriers": courier_list,
        }


# Register
registry.register(get_courier_availability, mutation=False)
