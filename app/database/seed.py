"""
RescueFlow AI — Seed Data.

Populates the database with realistic delivery-operations data including
five deliberate scenarios for demonstration:

  A) Easy reschedule (customer available, preferred slot open)
  B) Preferred slot unavailable → agent finds alternative
  C) Courier unavailable → reassignment needed
  D) Repeated delivery failure → escalation with memory
  E) No feasible option → immediate escalation

Run directly:  python -m app.database.seed
"""

from __future__ import annotations

import sys
from datetime import datetime, date, time, timedelta

from app.database.engine import engine, init_db, get_db
from app.database.models import (
    Base, Customer, Order, Delivery, Courier,
    DeliveryAttempt, Incident, AgentMemory,
)


def seed_all() -> None:
    """Drop + recreate tables and insert all seed data."""
    print("[*] Dropping existing tables...")
    Base.metadata.drop_all(bind=engine)

    print("[*] Creating tables...")
    init_db()

    with get_db() as db:
        # ── Customers (10) ────────────────────────────
        customers = [
            Customer(id=1, name="Aarav Sharma", phone="+91-9876543210", email="aarav@example.com",
                     address="12 MG Road, Bengaluru 560001",
                     preferred_delivery_time="morning", preferred_contact_method="sms",
                     special_instructions="Ring doorbell twice"),
            Customer(id=2, name="Priya Patel", phone="+91-9876543211", email="priya@example.com",
                     address="45 Linking Road, Mumbai 400050",
                     preferred_delivery_time="afternoon", preferred_contact_method="email",
                     special_instructions=None),
            Customer(id=3, name="Rohan Gupta", phone="+91-9876543212", email="rohan@example.com",
                     address="78 Park Street, Kolkata 700016",
                     preferred_delivery_time="morning", preferred_contact_method="call",
                     special_instructions="Leave with security guard if unavailable"),
            Customer(id=4, name="Sneha Reddy", phone="+91-9876543213", email="sneha@example.com",
                     address="23 Jubilee Hills, Hyderabad 500033",
                     preferred_delivery_time="evening", preferred_contact_method="sms",
                     special_instructions=None),
            Customer(id=5, name="Vikram Singh", phone="+91-9876543214", email="vikram@example.com",
                     address="56 Civil Lines, Delhi 110054",
                     preferred_delivery_time="morning", preferred_contact_method="call",
                     special_instructions="Call before delivery"),
            Customer(id=6, name="Ananya Desai", phone="+91-9876543215", email="ananya@example.com",
                     address="89 Anna Salai, Chennai 600002",
                     preferred_delivery_time="afternoon", preferred_contact_method="email",
                     special_instructions=None),
            Customer(id=7, name="Karthik Nair", phone="+91-9876543216", email="karthik@example.com",
                     address="34 MG Road, Kochi 682016",
                     preferred_delivery_time="morning", preferred_contact_method="sms",
                     special_instructions="Fragile items — handle with care"),
            Customer(id=8, name="Meera Joshi", phone="+91-9876543217", email="meera@example.com",
                     address="67 FC Road, Pune 411004",
                     preferred_delivery_time="afternoon", preferred_contact_method="call",
                     special_instructions=None),
            Customer(id=9, name="Arjun Kumar", phone="+91-9876543218", email="arjun@example.com",
                     address="90 Brigade Road, Bengaluru 560025",
                     preferred_delivery_time="morning", preferred_contact_method="sms",
                     special_instructions=None),
            Customer(id=10, name="Divya Menon", phone="+91-9876543219", email="divya@example.com",
                      address="12 Residency Road, Bengaluru 560071",
                      preferred_delivery_time="evening", preferred_contact_method="email",
                      special_instructions="Leave at front desk"),
        ]
        db.add_all(customers)
        db.flush()

        # ── Couriers (10) ─────────────────────────────
        couriers = [
            Courier(id=1, name="Ravi Kumar", vehicle_type="bike", status="active",
                    service_area="Bengaluru", current_location="MG Road Hub",
                    available_from=time(8, 0), available_until=time(18, 0)),
            Courier(id=2, name="Sunil Verma", vehicle_type="van", status="active",
                    service_area="Bengaluru", current_location="Whitefield Hub",
                    available_from=time(9, 0), available_until=time(20, 0)),
            Courier(id=3, name="Amit Yadav", vehicle_type="bike", status="active",
                    service_area="Mumbai", current_location="Andheri Hub",
                    available_from=time(8, 0), available_until=time(17, 0)),
            Courier(id=4, name="Deepak Nair", vehicle_type="van", status="active",
                    service_area="Kolkata", current_location="Park Street Hub",
                    available_from=time(10, 0), available_until=time(19, 0)),
            Courier(id=5, name="Manoj Pillai", vehicle_type="bike", status="inactive",
                    service_area="Hyderabad", current_location="Jubilee Hills Hub",
                    available_from=time(8, 0), available_until=time(16, 0)),
            Courier(id=6, name="Sanjay Rao", vehicle_type="bike", status="active",
                    service_area="Delhi", current_location="Connaught Place Hub",
                    available_from=time(9, 0), available_until=time(18, 0)),
            Courier(id=7, name="Prakash Iyer", vehicle_type="van", status="active",
                    service_area="Chennai", current_location="Anna Salai Hub",
                    available_from=time(8, 0), available_until=time(17, 0)),
            Courier(id=8, name="Rajesh Menon", vehicle_type="bike", status="active",
                    service_area="Kochi", current_location="MG Road Hub Kochi",
                    available_from=time(9, 0), available_until=time(18, 0)),
            Courier(id=9, name="Arun Pandey", vehicle_type="bike", status="on_break",
                    service_area="Pune", current_location="FC Road Hub",
                    available_from=time(8, 0), available_until=time(17, 0)),
            Courier(id=10, name="Vijay Sharma", vehicle_type="van", status="active",
                     service_area="Bengaluru", current_location="Jayanagar Hub",
                     available_from=time(12, 0), available_until=time(20, 0)),
        ]
        db.add_all(couriers)
        db.flush()

        today = date(2026, 9, 13)
        tomorrow = today + timedelta(days=1)
        day_after = today + timedelta(days=2)

        # ── Orders (20) ──────────────────────────────
        orders = [
            # Scenario A — easy reschedule (customer 1, order 1)
            Order(id=1, order_number="ORD-1001", customer_id=1, warehouse_id="WH-01",
                  package_size="medium", priority="standard", status="IN_TRANSIT",
                  expected_delivery_date=today),
            # Scenario B — preferred slot unavailable (customer 2, order 2)
            Order(id=2, order_number="ORD-1002", customer_id=2, warehouse_id="WH-02",
                  package_size="small", priority="express", status="IN_TRANSIT",
                  expected_delivery_date=today),
            # Scenario C — courier unavailable (customer 4, order 3)
            Order(id=3, order_number="ORD-1003", customer_id=4, warehouse_id="WH-01",
                  package_size="large", priority="standard", status="IN_TRANSIT",
                  expected_delivery_date=today),
            # Scenario D — repeated failure (customer 3, order 4)
            Order(id=4, order_number="ORD-1004", customer_id=3, warehouse_id="WH-01",
                  package_size="medium", priority="critical", status="IN_TRANSIT",
                  expected_delivery_date=today),
            # Scenario E — no feasible option (customer 5, order 5)
            Order(id=5, order_number="ORD-1005", customer_id=5, warehouse_id="WH-03",
                  package_size="large", priority="standard", status="IN_TRANSIT",
                  expected_delivery_date=today),
            # Extra orders for variety
            Order(id=6, order_number="ORD-1006", customer_id=6, warehouse_id="WH-02",
                  package_size="small", priority="standard", status="DELIVERED",
                  expected_delivery_date=today - timedelta(days=2)),
            Order(id=7, order_number="ORD-1007", customer_id=7, warehouse_id="WH-01",
                  package_size="medium", priority="express", status="IN_TRANSIT",
                  expected_delivery_date=today),
            Order(id=8, order_number="ORD-1008", customer_id=8, warehouse_id="WH-02",
                  package_size="small", priority="standard", status="PENDING",
                  expected_delivery_date=tomorrow),
            Order(id=9, order_number="ORD-1009", customer_id=9, warehouse_id="WH-01",
                  package_size="medium", priority="standard", status="IN_TRANSIT",
                  expected_delivery_date=today),
            Order(id=10, order_number="ORD-1010", customer_id=10, warehouse_id="WH-01",
                   package_size="large", priority="express", status="IN_TRANSIT",
                   expected_delivery_date=today),
            Order(id=11, order_number="ORD-1011", customer_id=1, warehouse_id="WH-01",
                   package_size="small", priority="standard", status="DELIVERED",
                   expected_delivery_date=today - timedelta(days=5)),
            Order(id=12, order_number="ORD-1012", customer_id=2, warehouse_id="WH-02",
                   package_size="medium", priority="standard", status="DELIVERED",
                   expected_delivery_date=today - timedelta(days=3)),
            Order(id=13, order_number="ORD-1013", customer_id=3, warehouse_id="WH-01",
                   package_size="small", priority="express", status="DELIVERED",
                   expected_delivery_date=today - timedelta(days=7)),
            Order(id=14, order_number="ORD-1014", customer_id=4, warehouse_id="WH-01",
                   package_size="medium", priority="standard", status="DELIVERED",
                   expected_delivery_date=today - timedelta(days=4)),
            Order(id=15, order_number="ORD-1015", customer_id=5, warehouse_id="WH-03",
                   package_size="large", priority="standard", status="DELIVERED",
                   expected_delivery_date=today - timedelta(days=6)),
            Order(id=16, order_number="ORD-1016", customer_id=6, warehouse_id="WH-02",
                   package_size="small", priority="standard", status="PENDING",
                   expected_delivery_date=tomorrow),
            Order(id=17, order_number="ORD-1017", customer_id=7, warehouse_id="WH-01",
                   package_size="medium", priority="standard", status="IN_TRANSIT",
                   expected_delivery_date=today),
            Order(id=18, order_number="ORD-1018", customer_id=8, warehouse_id="WH-02",
                   package_size="small", priority="express", status="IN_TRANSIT",
                   expected_delivery_date=today),
            Order(id=19, order_number="ORD-1019", customer_id=9, warehouse_id="WH-01",
                   package_size="medium", priority="standard", status="DELIVERED",
                   expected_delivery_date=today - timedelta(days=1)),
            Order(id=20, order_number="ORD-1020", customer_id=10, warehouse_id="WH-01",
                   package_size="large", priority="critical", status="IN_TRANSIT",
                   expected_delivery_date=today),
        ]
        db.add_all(orders)
        db.flush()

        # ── Deliveries ───────────────────────────────
        deliveries = [
            # Scenario A — courier 1, morning slot today, 1 attempt (failed)
            Delivery(id=1, order_id=1, courier_id=1, status="FAILED",
                     scheduled_date=today, scheduled_start=time(9, 0), scheduled_end=time(11, 0),
                     attempt_count=1, current_location="Near MG Road"),
            # Scenario B — courier 3, afternoon slot today (failed)
            Delivery(id=2, order_id=2, courier_id=3, status="FAILED",
                     scheduled_date=today, scheduled_start=time(14, 0), scheduled_end=time(16, 0),
                     attempt_count=1, current_location="Near Linking Road"),
            # Scenario C — courier 5 (inactive!), morning slot today (failed)
            Delivery(id=3, order_id=3, courier_id=5, status="FAILED",
                     scheduled_date=today, scheduled_start=time(10, 0), scheduled_end=time(12, 0),
                     attempt_count=1, current_location="Jubilee Hills area"),
            # Scenario D — courier 4, 3 failed attempts
            Delivery(id=4, order_id=4, courier_id=4, status="FAILED",
                     scheduled_date=today, scheduled_start=time(10, 0), scheduled_end=time(12, 0),
                     attempt_count=3, current_location="Park Street area"),
            # Scenario E — courier 6, Delhi (no couriers available tomorrow)
            Delivery(id=5, order_id=5, courier_id=6, status="FAILED",
                     scheduled_date=today, scheduled_start=time(9, 0), scheduled_end=time(11, 0),
                     attempt_count=1, current_location="Civil Lines area"),
            Delivery(id=6, order_id=6, courier_id=7, status="DELIVERED",
                     scheduled_date=today - timedelta(days=2),
                     scheduled_start=time(14, 0), scheduled_end=time(16, 0),
                     attempt_count=1, current_location="Anna Salai"),
            Delivery(id=7, order_id=7, courier_id=8, status="SCHEDULED",
                     scheduled_date=today, scheduled_start=time(10, 0), scheduled_end=time(12, 0),
                     attempt_count=0, current_location="MG Road Hub Kochi"),
            Delivery(id=8, order_id=9, courier_id=1, status="SCHEDULED",
                     scheduled_date=today, scheduled_start=time(14, 0), scheduled_end=time(16, 0),
                     attempt_count=0, current_location="Brigade Road area"),
            Delivery(id=9, order_id=10, courier_id=10, status="IN_TRANSIT",
                     scheduled_date=today, scheduled_start=time(14, 0), scheduled_end=time(16, 0),
                     attempt_count=0, current_location="Residency Road area"),
            Delivery(id=10, order_id=20, courier_id=2, status="IN_TRANSIT",
                      scheduled_date=today, scheduled_start=time(16, 0), scheduled_end=time(18, 0),
                      attempt_count=0, current_location="Jayanagar area"),
        ]
        db.add_all(deliveries)
        db.flush()

        # ── Delivery Attempts ────────────────────────
        attempts = [
            # Scenario A — 1 failed attempt
            DeliveryAttempt(delivery_id=1, attempt_number=1,
                           timestamp=datetime(2026, 9, 13, 10, 30),
                           reason="customer_unavailable",
                           location="12 MG Road, Bengaluru",
                           notes="Customer not home. Doorbell rang, no response."),
            # Scenario B — 1 failed attempt
            DeliveryAttempt(delivery_id=2, attempt_number=1,
                           timestamp=datetime(2026, 9, 13, 14, 45),
                           reason="courier_delayed",
                           location="45 Linking Road, Mumbai",
                           notes="Courier delayed 45 minutes due to traffic. Delivery window missed."),
            # Scenario C — 1 failed attempt (courier became inactive)
            DeliveryAttempt(delivery_id=3, attempt_number=1,
                           timestamp=datetime(2026, 9, 13, 10, 15),
                           reason="courier_unavailable",
                           location="23 Jubilee Hills, Hyderabad",
                           notes="Courier marked inactive mid-shift due to vehicle breakdown."),
            # Scenario D — 3 failed attempts
            DeliveryAttempt(delivery_id=4, attempt_number=1,
                           timestamp=datetime(2026, 9, 11, 10, 30),
                           reason="customer_unavailable",
                           location="78 Park Street, Kolkata",
                           notes="No one home. Left notice."),
            DeliveryAttempt(delivery_id=4, attempt_number=2,
                           timestamp=datetime(2026, 9, 12, 11, 0),
                           reason="customer_unavailable",
                           location="78 Park Street, Kolkata",
                           notes="Called customer, no answer. Left second notice."),
            DeliveryAttempt(delivery_id=4, attempt_number=3,
                           timestamp=datetime(2026, 9, 13, 10, 45),
                           reason="customer_unavailable",
                           location="78 Park Street, Kolkata",
                           notes="Third attempt. Security says customer travelling. Priority critical."),
            # Scenario E — 1 attempt
            DeliveryAttempt(delivery_id=5, attempt_number=1,
                           timestamp=datetime(2026, 9, 13, 9, 30),
                           reason="delivery_slot_missed",
                           location="56 Civil Lines, Delhi",
                           notes="Courier arrived late, customer left for work."),
            # Historical data for other deliveries
            DeliveryAttempt(delivery_id=6, attempt_number=1,
                           timestamp=datetime(2026, 9, 11, 15, 0),
                           reason="delivered",
                           location="89 Anna Salai, Chennai",
                           notes="Delivered successfully."),
        ]
        # Additional historical attempts for customer 1 (via order 11)
        # We need a delivery for order 11 first
        hist_del_1 = Delivery(id=11, order_id=11, courier_id=1, status="DELIVERED",
                              scheduled_date=today - timedelta(days=5),
                              scheduled_start=time(9, 0), scheduled_end=time(11, 0),
                              attempt_count=1, current_location="MG Road")
        db.add(hist_del_1)
        db.flush()
        attempts.append(
            DeliveryAttempt(delivery_id=11, attempt_number=1,
                           timestamp=datetime(2026, 9, 8, 9, 45),
                           reason="delivered",
                           location="12 MG Road, Bengaluru",
                           notes="Delivered in morning slot. Customer was home.")
        )

        # Historical delivery for customer 3 showing past resolution
        hist_del_3 = Delivery(id=13, order_id=13, courier_id=4, status="DELIVERED",
                              scheduled_date=today - timedelta(days=7),
                              scheduled_start=time(10, 0), scheduled_end=time(12, 0),
                              attempt_count=2, current_location="Park Street")
        db.add(hist_del_3)
        db.flush()
        attempts.extend([
            DeliveryAttempt(delivery_id=13, attempt_number=1,
                           timestamp=datetime(2026, 9, 6, 10, 30),
                           reason="customer_unavailable",
                           location="78 Park Street, Kolkata",
                           notes="Customer not home."),
            DeliveryAttempt(delivery_id=13, attempt_number=2,
                           timestamp=datetime(2026, 9, 7, 10, 0),
                           reason="delivered",
                           location="78 Park Street, Kolkata",
                           notes="Left with security guard per customer instructions."),
        ])

        db.add_all(attempts)
        db.flush()

        # ── Incidents (10) ───────────────────────────
        incidents = [
            # Scenario A — INC-001
            Incident(id=1, order_id=1, incident_type="customer_unavailable",
                     severity="medium",
                     description="Customer Aarav Sharma was unavailable during scheduled delivery window 09:00-11:00. Doorbell rang with no response.",
                     status="OPEN"),
            # Scenario B — INC-002
            Incident(id=2, order_id=2, incident_type="courier_delayed",
                     severity="medium",
                     description="Courier delayed by 45 minutes due to traffic congestion. Original afternoon delivery window 14:00-16:00 was missed for customer Priya Patel.",
                     status="OPEN"),
            # Scenario C — INC-003
            Incident(id=3, order_id=3, incident_type="courier_unavailable",
                     severity="high",
                     description="Assigned courier Manoj Pillai became unavailable mid-shift (vehicle breakdown). Delivery to Sneha Reddy cannot proceed.",
                     status="OPEN"),
            # Scenario D — INC-004
            Incident(id=4, order_id=4, incident_type="repeated_delivery_failure",
                     severity="critical",
                     description="Third consecutive failed delivery attempt for Rohan Gupta. Customer has been unavailable on 2026-09-11, 2026-09-12, and 2026-09-13. Priority is critical.",
                     status="OPEN"),
            # Scenario E — INC-005
            Incident(id=5, order_id=5, incident_type="delivery_slot_missed",
                     severity="high",
                     description="Delivery slot missed for Vikram Singh. Courier arrived late, customer had already left for work. No alternative couriers available in Delhi service area.",
                     status="OPEN"),
            # Extra incidents
            Incident(id=6, order_id=7, incident_type="address_issue",
                     severity="medium",
                     description="Courier reports address for Karthik Nair is incomplete. Building number missing.",
                     status="OPEN"),
            Incident(id=7, order_id=9, incident_type="customer_unavailable",
                     severity="low",
                     description="Arjun Kumar not available during afternoon slot. First attempt.",
                     status="OPEN"),
            Incident(id=8, order_id=10, incident_type="courier_delayed",
                     severity="medium",
                     description="Courier delayed for Divya Menon delivery. Estimated 30 min delay.",
                     status="OPEN"),
            Incident(id=9, order_id=17, incident_type="failed_delivery_attempt",
                     severity="medium",
                     description="Failed delivery for Karthik Nair second order. Fragile items concern.",
                     status="OPEN"),
            Incident(id=10, order_id=20, incident_type="courier_delayed",
                      severity="high",
                      description="Critical priority order for Divya Menon. Courier delayed, SLA at risk.",
                      status="OPEN"),
        ]
        db.add_all(incidents)
        db.flush()

        # ── Agent Memory ─────────────────────────────
        memories = [
            # Customer 1 (Aarav) — morning preference + past success
            AgentMemory(customer_id=1, memory_type="preference",
                        content="Customer strongly prefers morning delivery (09:00-12:00). Has been successfully delivered to in morning slots.",
                        importance=0.9),
            AgentMemory(customer_id=1, memory_type="resolution",
                        content="Previous delivery issue resolved by rescheduling to morning slot on 2026-09-08. Customer was home and accepted delivery.",
                        importance=0.8),
            AgentMemory(customer_id=1, memory_type="observation",
                        content="Customer typically not home in afternoons. Works from office.",
                        importance=0.7),

            # Customer 2 (Priya) — afternoon preference
            AgentMemory(customer_id=2, memory_type="preference",
                        content="Customer prefers afternoon delivery. Works from home in afternoons.",
                        importance=0.8),

            # Customer 3 (Rohan) — security guard fallback + repeated issues
            AgentMemory(customer_id=3, memory_type="preference",
                        content="Customer prefers morning delivery. Frequently travels for work.",
                        importance=0.8),
            AgentMemory(customer_id=3, memory_type="resolution",
                        content="Past delivery successfully completed by leaving package with security guard as per customer instructions.",
                        importance=0.9),
            AgentMemory(customer_id=3, memory_type="observation",
                        content="Customer has had multiple unavailability issues. Travel schedule is unpredictable.",
                        importance=0.7),
            AgentMemory(customer_id=3, memory_type="escalation",
                        content="Customer contacted support after second failed attempt on previous order. Requested guard handoff as standard procedure.",
                        importance=0.85),

            # Customer 4 (Sneha) — evening preference
            AgentMemory(customer_id=4, memory_type="preference",
                        content="Customer prefers evening delivery after 17:00.",
                        importance=0.8),

            # Customer 5 (Vikram) — morning preference, strict schedule
            AgentMemory(customer_id=5, memory_type="preference",
                        content="Customer leaves for work at 09:30 sharp. Delivery must arrive before 09:30 or after 18:00.",
                        importance=0.9),
            AgentMemory(customer_id=5, memory_type="observation",
                        content="Customer has explicitly stated no neighbors or guards to accept delivery.",
                        importance=0.85),
        ]
        db.add_all(memories)

    print("[OK] Seed data loaded successfully!")
    print("   - 10 customers")
    print("   - 20 orders")
    print("   - 10 couriers")
    print("   - 12 deliveries")
    print("   - 10+ delivery attempts")
    print("   - 10 incidents")
    print("   - 11 memory entries")
    print("   - 5 demo scenarios (A-E)")


if __name__ == "__main__":
    seed_all()
