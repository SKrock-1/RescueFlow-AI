"""
RescueFlow AI — Tool Unit Tests.

Validates read and mutation tools independently.
"""

import pytest
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


def test_get_order_success():
    result = get_order(1)
    assert result["success"] is True
    assert result["order_id"] == 1
    assert result["order_number"] == "ORD-1001"
    assert "delivery_status" in result


def test_get_order_not_found():
    result = get_order(99999)
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_get_customer_profile_success():
    result = get_customer_profile(1)
    assert result["success"] is True
    assert result["name"] == "Aarav Sharma"
    assert result["preferred_delivery_time"] == "morning"
    assert len(result["memories"]) > 0


def test_get_customer_profile_not_found():
    result = get_customer_profile(99999)
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_get_courier_availability():
    result = get_courier_availability(area="Bengaluru", date="2026-09-14")
    assert result["success"] is True
    assert result["available_couriers_count"] >= 1
    for c in result["couriers"]:
        assert c["status"] == "active"


def test_find_available_delivery_slots():
    result = find_available_delivery_slots(customer_id=1, date="2026-09-14")
    assert result["success"] is True
    assert result["slots_count"] > 0
    # Must have morning slot that matches preference
    morning_slots = [s for s in result["slots"] if s["matches_preference"]]
    assert len(morning_slots) >= 1
    assert morning_slots[0]["score"] > 0


def test_reschedule_delivery_success():
    result = reschedule_delivery(
        order_id=1,
        date="2026-09-14",
        start_time="10:00",
        end_time="12:00",
    )
    assert result["success"] is True
    assert result["status"] == "RESCHEDULED"
    assert result["new_date"] == "2026-09-14"
    assert "10:00 - 12:00" in result["new_slot"]


def test_reschedule_delivery_invalid_times():
    # End time earlier than start time
    result = reschedule_delivery(
        order_id=1,
        date="2026-09-14",
        start_time="15:00",
        end_time="11:00",
    )
    assert result["success"] is False
    assert "strictly before" in result["reason"].lower()


def test_reschedule_delivery_order_not_found():
    result = reschedule_delivery(
        order_id=99999,
        date="2026-09-14",
        start_time="10:00",
        end_time="12:00",
    )
    assert result["success"] is False
    assert "does not exist" in result["reason"].lower()


def test_reassign_courier_success():
    result = reassign_courier(order_id=3, courier_id=1)
    assert result["success"] is True
    assert result["new_courier_id"] == 1
    assert result["status"] == "REASSIGNED"


def test_reassign_courier_inactive():
    # Courier 5 is marked inactive in seed data
    result = reassign_courier(order_id=3, courier_id=5)
    assert result["success"] is False
    assert "inactive" in result["reason"].lower()


def test_update_delivery_status():
    result = update_delivery_status(order_id=1, status="IN_TRANSIT")
    assert result["success"] is True
    assert result["status"] == "IN_TRANSIT"

    # Invalid status
    invalid_result = update_delivery_status(order_id=1, status="INVALID_STATUS")
    assert invalid_result["success"] is False


def test_get_delivery_history():
    result = get_delivery_history(order_id=4)
    assert result["success"] is True
    assert result["attempt_count"] == 3
    assert len(result["attempts"]) == 3
    assert result["attempts"][0]["reason"] == "customer_unavailable"


def test_escalate_incident():
    result = escalate_incident(order_id=4, reason="3 failed delivery attempts, customer travelling.")
    assert result["success"] is True
    assert result["status"] == "ESCALATED"
