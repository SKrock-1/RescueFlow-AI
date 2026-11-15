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
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# Valid state transitions
VALID_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.INVESTIGATING: {
        AgentStatus.INVESTIGATING,
        AgentStatus.EVALUATING,
        AgentStatus.ACTING,
        AgentStatus.AWAITING_APPROVAL,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.EVALUATING: {
        AgentStatus.EVALUATING,
        AgentStatus.ACTING,
        AgentStatus.AWAITING_APPROVAL,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.ACTING: {
        AgentStatus.VERIFYING,
        AgentStatus.AWAITING_APPROVAL,
        AgentStatus.ESCALATED,
        AgentStatus.FAILED,
    },
    AgentStatus.AWAITING_APPROVAL: {
        AgentStatus.ACTING,
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


# States a run may end in. AWAITING_APPROVAL pauses the run for a person.
FINISH_STATES = {
    AgentStatus.AWAITING_APPROVAL,
    AgentStatus.RESOLVED,
    AgentStatus.ESCALATED,
    AgentStatus.FAILED,
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

    def finish(self, new_status: AgentStatus) -> None:
        """End the run in a terminal state (or paused for approval), with validation.

        Any in-progress state may finish; a run that already finished, or is
        paused for approval, cannot be finished again with a different outcome.
        """
        if new_status not in FINISH_STATES:
            raise ValueError(f"{new_status.value} is not a finishing state.")
        if new_status == self.status:
            return
        if self.is_finished() or self.status == AgentStatus.AWAITING_APPROVAL:
            raise ValueError(
                f"Run already ended as {self.status.value}; cannot change it to {new_status.value}."
            )
        self.status = new_status

    def is_finished(self) -> bool:
        """Check if terminal state is reached."""
        return self.status in {
            AgentStatus.RESOLVED,
            AgentStatus.ESCALATED,
            AgentStatus.FAILED,
        }
