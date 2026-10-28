"""
RescueFlow AI — Pydantic Schemas.

Structured I/O contracts used by tools, agent, services, and UI.
These are *not* ORM models — they are serializable data transfer objects.
"""

from __future__ import annotations

from datetime import datetime, date, time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ────────────────────────────────────────────
# Enums
# ────────────────────────────────────────────

class ActionType(str, Enum):
    RESCHEDULE = "RESCHEDULE"
    REASSIGN_COURIER = "REASSIGN_COURIER"
    CHANGE_SLOT = "CHANGE_SLOT"
    UPDATE_STATUS = "UPDATE_STATUS"
    ESCALATE = "ESCALATE"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ────────────────────────────────────────────
# Tool I/O Schemas
# ────────────────────────────────────────────

class OrderInfo(BaseModel):
    """Structured order information returned by get_order."""
    order_id: int
    order_number: str
    customer_id: int
    customer_name: str
    warehouse_id: str
    package_size: str
    priority: str
    status: str
    expected_delivery_date: str | None = None
    delivery_status: str | None = None
    delivery_courier_id: int | None = None
    delivery_scheduled_date: str | None = None
    delivery_scheduled_start: str | None = None
    delivery_scheduled_end: str | None = None
    delivery_attempt_count: int = 0


class CustomerProfile(BaseModel):
    """Structured customer profile returned by get_customer_profile."""
    customer_id: int
    name: str
    phone: str
    email: str | None = None
    address: str
    preferred_delivery_time: str | None = None
    preferred_contact_method: str | None = None
    special_instructions: str | None = None
    memory: list[MemoryEntry] = Field(default_factory=list)


class MemoryEntry(BaseModel):
    """A single memory fact about a customer."""
    memory_type: str
    content: str
    importance: float
    created_at: str | None = None


# Resolve forward reference
CustomerProfile.model_rebuild()


class DeliveryAttemptInfo(BaseModel):
    """A single delivery attempt record."""
    attempt_number: int
    timestamp: str
    reason: str
    location: str | None = None
    notes: str | None = None


class DeliveryHistoryInfo(BaseModel):
    """Delivery history for an order."""
    order_id: int
    order_number: str
    delivery_status: str
    attempt_count: int
    attempts: list[DeliveryAttemptInfo] = Field(default_factory=list)


class CourierInfo(BaseModel):
    """Available courier information."""
    courier_id: int
    name: str
    vehicle_type: str
    status: str
    service_area: str
    available_from: str
    available_until: str
    current_location: str | None = None


class DeliverySlot(BaseModel):
    """A candidate delivery slot."""
    date: str
    start_time: str
    end_time: str
    courier_id: int
    courier_name: str
    matches_preference: bool = False
    score: float = 0.0


class ToolResult(BaseModel):
    """Standardized result from any tool execution."""
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    reason: str | None = None


# ────────────────────────────────────────────
# Candidate Action
# ────────────────────────────────────────────

class CandidateAction(BaseModel):
    """A recovery action being considered by the agent."""
    action: ActionType
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    courier_id: int | None = None
    reason: str = ""
    score: float = 0.0
    feasible: bool = True


# ────────────────────────────────────────────
# Agent Trace
# ────────────────────────────────────────────

class TraceEvent(BaseModel):
    """A single event in the agent execution trace."""
    timestamp: str
    step_number: int
    event_type: str  # tool_call / decision / error / observation
    tool_name: str | None = None
    summary: str
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    status: str = "success"  # success / error / skipped


# ────────────────────────────────────────────
# Agent Result
# ────────────────────────────────────────────

class AgentResult(BaseModel):
    """Final structured output from the agent."""
    incident_id: int
    order_id: int
    customer_id: int
    status: str  # RESOLVED / ESCALATED / FAILED
    action_taken: str | None = None
    decision_summary: str
    trace: list[TraceEvent] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    memory_updates: list[str] = Field(default_factory=list)
    notifications: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
