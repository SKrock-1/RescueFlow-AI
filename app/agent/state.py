"""
RescueFlow AI — Agent State Management.

Defines the AgentStatus enum and the comprehensive AgentState object
with explicit transitions between states:
INVESTIGATING -> EVALUATING -> ACTING -> VERIFYING -> RESOLVED / ESCALATED / FAILED
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.models import CandidateAction, TraceEvent


class AgentStatus(str, Enum):
    """Explicit statuses through the agent lifecycle."""
    INVESTIGATING = "INVESTIGATING"
    EVALUATING = "EVALUATING"
    ACTING = "ACTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# Valid state transitions
VALID_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.INVESTIGATING: {
        AgentStatus.INVESTIGATING,
        AgentStatus.EVALUATING,
        AgentStatus.ACTING,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.EVALUATING: {
        AgentStatus.EVALUATING,
        AgentStatus.ACTING,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.ACTING: {
        AgentStatus.VERIFYING,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.VERIFYING: {
        AgentStatus.RESOLVED,
        AgentStatus.EVALUATING,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.RESOLVED: set(),
    AgentStatus.ESCALATED: set(),
    AgentStatus.FAILED: set(),
}


class AgentState(BaseModel):
    """The central state of the RescueFlow resolution agent."""
    incident_id: int
    order_id: int
    customer_id: int
    goal: str
    current_step: int = 0
    max_steps: int = 10
    status: AgentStatus = AgentStatus.INVESTIGATING

    observations: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    selected_action: CandidateAction | None = None
    memory: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def transition_to(self, new_status: AgentStatus) -> None:
        """Safely transition to a new status with validation."""
        if new_status == self.status:
            return

        allowed = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Illegal state transition from {self.status.value} to {new_status.value}."
            )
        self.status = new_status

    def is_finished(self) -> bool:
        """Check if terminal state is reached."""
        return self.status in {
            AgentStatus.RESOLVED,
            AgentStatus.ESCALATED,
            AgentStatus.FAILED,
        }
