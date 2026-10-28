"""
RescueFlow AI — SQLAlchemy ORM Models.

Eight models covering the full delivery-operations domain:
Customer, Order, Delivery, Courier, DeliveryAttempt,
Incident, AgentMemory, AgentRun.
"""

from __future__ import annotations

from datetime import datetime, date, time, timezone


def _utcnow() -> datetime:
    """Timezone-aware UTC now — replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)

from sqlalchemy import (
    Column, Integer, String, Text, Float, Date, Time, DateTime,
    ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""


# ────────────────────────────────────────────
# Customer
# ────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String(120), nullable=False)
    phone: str = Column(String(30), nullable=False)
    email: str = Column(String(120), nullable=True)
    address: str = Column(Text, nullable=False)
    preferred_delivery_time: str | None = Column(String(30), nullable=True)  # e.g. "morning"
    preferred_contact_method: str | None = Column(String(20), nullable=True)  # sms/email/call
    special_instructions: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, default=_utcnow)

    orders = relationship("Order", back_populates="customer")
    memories = relationship("AgentMemory", back_populates="customer")


# ────────────────────────────────────────────
# Order
# ────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    order_number: str = Column(String(30), unique=True, nullable=False)
    customer_id: int = Column(Integer, ForeignKey("customers.id"), nullable=False)
    warehouse_id: str = Column(String(20), nullable=False, default="WH-01")
    package_size: str = Column(String(20), nullable=False, default="medium")  # small/medium/large
    priority: str = Column(String(20), nullable=False, default="standard")  # standard/express/critical
    status: str = Column(String(30), nullable=False, default="PENDING")
    expected_delivery_date: date | None = Column(Date, nullable=True)
    created_at: datetime = Column(DateTime, default=_utcnow)

    customer = relationship("Customer", back_populates="orders")
    delivery = relationship("Delivery", back_populates="order", uselist=False)
    incidents = relationship("Incident", back_populates="order")


# ────────────────────────────────────────────
# Delivery
# ────────────────────────────────────────────

class Delivery(Base):
    __tablename__ = "deliveries"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    order_id: int = Column(Integer, ForeignKey("orders.id"), nullable=False)
    courier_id: int | None = Column(Integer, ForeignKey("couriers.id"), nullable=True)
    status: str = Column(String(30), nullable=False, default="SCHEDULED")
    scheduled_date: date | None = Column(Date, nullable=True)
    scheduled_start: time | None = Column(Time, nullable=True)
    scheduled_end: time | None = Column(Time, nullable=True)
    attempt_count: int = Column(Integer, nullable=False, default=0)
    current_location: str | None = Column(String(200), nullable=True)

    order = relationship("Order", back_populates="delivery")
    courier = relationship("Courier", back_populates="deliveries")
    attempts = relationship("DeliveryAttempt", back_populates="delivery", order_by="DeliveryAttempt.attempt_number")


# ────────────────────────────────────────────
# Courier
# ────────────────────────────────────────────

class Courier(Base):
    __tablename__ = "couriers"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String(120), nullable=False)
    vehicle_type: str = Column(String(30), nullable=False, default="bike")  # bike/van/truck
    status: str = Column(String(20), nullable=False, default="active")  # active/inactive/on_break
    service_area: str = Column(String(60), nullable=False)
    current_location: str | None = Column(String(200), nullable=True)
    available_from: time | None = Column(Time, nullable=True)
    available_until: time | None = Column(Time, nullable=True)

    deliveries = relationship("Delivery", back_populates="courier")


# ────────────────────────────────────────────
# DeliveryAttempt
# ────────────────────────────────────────────

class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id: int = Column(Integer, ForeignKey("deliveries.id"), nullable=False)
    attempt_number: int = Column(Integer, nullable=False)
    timestamp: datetime = Column(DateTime, default=_utcnow)
    reason: str = Column(String(100), nullable=True)
    location: str | None = Column(String(200), nullable=True)
    notes: str | None = Column(Text, nullable=True)

    delivery = relationship("Delivery", back_populates="attempts")


# ────────────────────────────────────────────
# Incident
# ────────────────────────────────────────────

class Incident(Base):
    __tablename__ = "incidents"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    order_id: int = Column(Integer, ForeignKey("orders.id"), nullable=False)
    incident_type: str = Column(String(60), nullable=False)
    severity: str = Column(String(20), nullable=False, default="medium")  # low/medium/high/critical
    description: str = Column(Text, nullable=False)
    status: str = Column(String(30), nullable=False, default="OPEN")
    agent_decision: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, default=_utcnow)
    resolved_at: datetime | None = Column(DateTime, nullable=True)

    order = relationship("Order", back_populates="incidents")
    agent_runs = relationship("AgentRun", back_populates="incident")


# ────────────────────────────────────────────
# AgentMemory
# ────────────────────────────────────────────

class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    customer_id: int = Column(Integer, ForeignKey("customers.id"), nullable=False)
    memory_type: str = Column(String(60), nullable=False)  # preference/resolution/escalation/observation
    content: str = Column(Text, nullable=False)
    importance: float = Column(Float, nullable=False, default=0.5)
    created_at: datetime = Column(DateTime, default=_utcnow)

    customer = relationship("Customer", back_populates="memories")


# ────────────────────────────────────────────
# AgentRun
# ────────────────────────────────────────────

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    incident_id: int = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    step_number: int = Column(Integer, nullable=False)
    action_type: str = Column(String(30), nullable=False)  # tool_call/decision/error
    tool_name: str | None = Column(String(60), nullable=True)
    arguments: str | None = Column(Text, nullable=True)  # JSON string
    result: str | None = Column(Text, nullable=True)  # JSON string
    decision: str | None = Column(Text, nullable=True)
    timestamp: datetime = Column(DateTime, default=_utcnow)

    incident = relationship("Incident", back_populates="agent_runs")
