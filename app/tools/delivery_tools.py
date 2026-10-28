"""
RescueFlow AI — Delivery Tools.

Read tools:
- get_delivery_history(order_id)
- find_available_delivery_slots(customer_id, date)

Mutation tools:
- reschedule_delivery(order_id, date, start_time, end_time)
- reassign_courier(order_id, courier_id)
- update_delivery_status(order_id, status)
"""

from __future__ import annotations

from datetime import datetime, date as date_cls, time as time_cls
import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import Order, Delivery, DeliveryAttempt, Courier, Customer
from app.tools.registry import registry
from app.services.scoring import score_option

logger = logging.getLogger(__name__)


def _parse_time(time_str: str) -> time_cls:
    """Parse HH:MM or HH:MM:SS string to time object."""
    parts = [int(p) for p in time_str.strip().split(":")]
    if len(parts) == 2:
        return time_cls(parts[0], parts[1])
    elif len(parts) >= 3:
        return time_cls(parts[0], parts[1], parts[2])
    raise ValueError(f"Invalid time format: {time_str}")


def _parse_date(date_str: str) -> date_cls:
    """Parse YYYY-MM-DD string to date object."""
    return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()


def get_delivery_history(order_id: int) -> dict[str, Any]:
    """Retrieve all delivery attempts and historical status for an order.

    order_id: The numeric ID of the order to check delivery attempts for.
    """
    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return {"success": False, "error": f"Order {order_id} not found"}

        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        if not delivery:
            return {
                "success": True,
                "order_id": order_id,
                "order_number": order.order_number,
                "delivery_status": "NONE",
                "attempt_count": 0,
                "attempts": [],
            }

        attempts = (
            db.query(DeliveryAttempt)
            .filter(DeliveryAttempt.delivery_id == delivery.id)
            .order_by(DeliveryAttempt.attempt_number.asc())
            .all()
        )

        attempt_list = [
            {
                "attempt_number": a.attempt_number,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "reason": a.reason,
                "location": a.location,
                "notes": a.notes,
            }
            for a in attempts
        ]

        logger.info("Retrieved delivery history for order %d: %d attempts", order_id, len(attempt_list))
        return {
            "success": True,
            "order_id": order_id,
            "order_number": order.order_number,
            "delivery_status": delivery.status,
            "attempt_count": delivery.attempt_count,
            "attempts": attempt_list,
        }


def find_available_delivery_slots(customer_id: int, date: str) -> dict[str, Any]:
    """Find and rank feasible delivery slots for a customer on a given date.

    customer_id: The numeric ID of the customer receiving delivery.
    date: The target delivery date (YYYY-MM-DD).
    """
    try:
        target_date = _parse_date(date)
    except Exception as exc:
        return {"success": False, "error": f"Invalid date format: {exc}"}

    with get_db() as db:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            return {"success": False, "error": f"Customer {customer_id} not found"}

        # Infer area from address or customer profile
        customer_address = customer.address or ""
        city_keywords = ["Bengaluru", "Mumbai", "Kolkata", "Hyderabad", "Delhi", "Chennai", "Pune", "Kochi"]
        target_city = "Bengaluru"
        for city in city_keywords:
            if city.lower() in customer_address.lower():
                target_city = city
                break

        # Query active couriers in that city
        couriers = (
            db.query(Courier)
            .filter(
                Courier.service_area.ilike(f"%{target_city}%"),
                Courier.status == "active",
            )
            .all()
        )

        if not couriers:
            logger.warning("No active couriers found in city %s for date %s", target_city, date)
            return {
                "success": True,
                "customer_id": customer_id,
                "target_date": date,
                "slots_count": 0,
                "slots": [],
                "note": f"No active couriers available in {target_city} for the selected date.",
            }

        standard_windows = [
            ("morning", time_cls(9, 0), time_cls(12, 0), "09:00", "12:00"),
            ("afternoon", time_cls(13, 0), time_cls(16, 0), "13:00", "16:00"),
            ("evening", time_cls(16, 0), time_cls(19, 0), "16:00", "19:00"),
        ]

        candidate_slots: list[dict[str, Any]] = []
        preferred_block = (customer.preferred_delivery_time or "").lower().strip()

        for courier in couriers:
            c_from = courier.available_from or time_cls(8, 0)
            c_until = courier.available_until or time_cls(20, 0)

            for block_name, start_t, end_t, start_str, end_str in standard_windows:
                # Check courier shift covers the slot
                if start_t >= c_from and end_t <= c_until:
                    matches = block_name == preferred_block

                    # Deterministic scoring
                    scored = score_option(
                        action="RESCHEDULE",
                        matches_preference=matches,
                        slot_available=True,
                        courier_available=True,
                        sla_hours_remaining=24.0,
                        estimated_delay_hours=12.0 if not matches else 4.0,
                        previous_attempt_count=0,
                        date=date,
                        start_time=start_str,
                        end_time=end_str,
                        courier_id=courier.id,
                        reason=f"{block_name.capitalize()} slot with courier {courier.name}",
                    )

                    candidate_slots.append({
                        "date": date,
                        "time_block": block_name,
                        "start_time": start_str,
                        "end_time": end_str,
                        "courier_id": courier.id,
                        "courier_name": courier.name,
                        "vehicle_type": courier.vehicle_type,
                        "matches_preference": matches,
                        "score": scored.total_score,
                        "breakdown": scored.breakdown,
                    })

        # Sort highest score first
        candidate_slots.sort(key=lambda s: s["score"], reverse=True)

        logger.info("Generated %d feasible slots for customer %d on %s", len(candidate_slots), customer_id, date)
        return {
            "success": True,
            "customer_id": customer_id,
            "target_date": date,
            "preferred_delivery_time": customer.preferred_delivery_time,
            "slots_count": len(candidate_slots),
            "slots": candidate_slots,
        }


def reschedule_delivery(order_id: int, date: str, start_time: str, end_time: str) -> dict[str, Any]:
    """Reschedule delivery for an order to a specified date and time window.

    order_id: The numeric ID of the order to reschedule.
    date: The new delivery date (format YYYY-MM-DD).
    start_time: The window start time (format HH:MM).
    end_time: The window end time (format HH:MM).
    """
    try:
        new_date = _parse_date(date)
        new_start = _parse_time(start_time)
        new_end = _parse_time(end_time)
    except Exception as exc:
        return {
            "success": False,
            "error": "Validation failed",
            "reason": f"Invalid date or time format: {exc}",
        }

    if new_start >= new_end:
        return {
            "success": False,
            "error": "Validation failed",
            "reason": f"Start time {start_time} must be strictly before end time {end_time}.",
        }

    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return {
                "success": False,
                "error": "Order not found",
                "reason": f"Order {order_id} does not exist in the database.",
            }

        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        if not delivery:
            # Create delivery if not existing
            delivery = Delivery(
                order_id=order_id,
                status="RESCHEDULED",
                scheduled_date=new_date,
                scheduled_start=new_start,
                scheduled_end=new_end,
                attempt_count=0,
            )
            db.add(delivery)
        else:
            delivery.scheduled_date = new_date
            delivery.scheduled_start = new_start
            delivery.scheduled_end = new_end
            delivery.status = "RESCHEDULED"

        # Update order expected delivery date and status
        order.expected_delivery_date = new_date
        order.status = "IN_TRANSIT"

        db.flush()

        logger.info(
            "Successfully rescheduled order %d to %s %s-%s",
            order_id, date, start_time, end_time
        )
        return {
            "success": True,
            "order_id": order_id,
            "order_number": order.order_number,
            "new_date": date,
            "new_slot": f"{start_time} - {end_time}",
            "status": "RESCHEDULED",
            "message": f"Delivery successfully rescheduled for {date} from {start_time} to {end_time}.",
        }


def reassign_courier(order_id: int, courier_id: int) -> dict[str, Any]:
    """Reassign delivery of an order to a different active courier.

    order_id: The numeric ID of the order.
    courier_id: The numeric ID of the new courier to assign.
    """
    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return {"success": False, "error": f"Order {order_id} not found", "reason": "Order does not exist"}

        courier = db.query(Courier).filter(Courier.id == courier_id).first()
        if not courier:
            return {"success": False, "error": f"Courier {courier_id} not found", "reason": "Courier does not exist"}

        if courier.status != "active":
            return {
                "success": False,
                "error": "Courier inactive",
                "reason": f"Courier '{courier.name}' is currently {courier.status} and cannot be assigned.",
            }

        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        if not delivery:
            delivery = Delivery(order_id=order_id, courier_id=courier_id, status="SCHEDULED")
            db.add(delivery)
        else:
            delivery.courier_id = courier_id
            delivery.status = "REASSIGNED"

        db.flush()

        logger.info("Order %d reassigned to courier %s (ID %d)", order_id, courier.name, courier.id)
        return {
            "success": True,
            "order_id": order_id,
            "new_courier_id": courier.id,
            "courier_name": courier.name,
            "vehicle_type": courier.vehicle_type,
            "status": "REASSIGNED",
            "message": f"Order {order_id} successfully reassigned to courier {courier.name}.",
        }


def update_delivery_status(order_id: int, status: str) -> dict[str, Any]:
    """Update delivery and order operational status.

    order_id: The numeric ID of the order.
    status: The new status string (e.g. 'IN_TRANSIT', 'SCHEDULED', 'RESCHEDULED', 'ESCALATED', 'FAILED').
    """
    valid_statuses = {"SCHEDULED", "IN_TRANSIT", "RESCHEDULED", "DELIVERED", "FAILED", "ESCALATED", "ON_HOLD"}
    clean_status = status.upper().strip()

    if clean_status not in valid_statuses:
        return {
            "success": False,
            "error": "Invalid status",
            "reason": f"Status '{status}' is invalid. Allowed: {sorted(list(valid_statuses))}",
        }

    with get_db() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return {"success": False, "error": f"Order {order_id} not found", "reason": "Order does not exist"}

        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        if delivery:
            delivery.status = clean_status
        order.status = clean_status

        db.flush()

        logger.info("Updated status of order %d to %s", order_id, clean_status)
        return {
            "success": True,
            "order_id": order_id,
            "status": clean_status,
            "message": f"Order {order_id} status updated to {clean_status}.",
        }


# Register all tools with registry
registry.register(get_delivery_history, mutation=False)
registry.register(find_available_delivery_slots, mutation=False)
registry.register(reschedule_delivery, mutation=True)
registry.register(reassign_courier, mutation=True)
registry.register(update_delivery_status, mutation=True)
