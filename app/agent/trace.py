"""
RescueFlow AI — Execution Trace Recorder.

Records all actions, tool calls, arguments, observations, and decisions
both in-memory and persistently into the AgentRun database table.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import AgentRun
from app.schemas.models import TraceEvent

logger = logging.getLogger(__name__)


class AgentTrace:
    """Collects and persists chronological steps in an agent run."""

    def __init__(self, incident_id: int) -> None:
        self.incident_id = incident_id
        self.events: list[TraceEvent] = []

    def record_step(
        self,
        step_number: int,
        event_type: str,
        summary: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        status: str = "success",
    ) -> TraceEvent:
        """Record an event in the execution trace and persist to database."""
        event = TraceEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            step_number=step_number,
            event_type=event_type,
            tool_name=tool_name,
            summary=summary,
            arguments=arguments,
            result=result,
            status=status,
        )
        self.events.append(event)

        # Persist to database
        try:
            with get_db() as db:
                run_entry = AgentRun(
                    incident_id=self.incident_id,
                    step_number=step_number,
                    action_type=event_type,
                    tool_name=tool_name,
                    arguments=json.dumps(arguments, default=str) if arguments else None,
                    result=json.dumps(result, default=str) if result else None,
                    decision=summary if event_type == "decision" else None,
                    timestamp=datetime.now(timezone.utc),
                )
                db.add(run_entry)
        except Exception as exc:
            logger.error("Failed to persist AgentRun entry: %s", exc)

        logger.info(
            "TRACE [Step %d] [%s] %s %s",
            step_number, event_type.upper(), tool_name or "", summary
        )
        return event

    def to_list(self) -> list[dict[str, Any]]:
        """Return trace events as dicts."""
        return [e.model_dump() for e in self.events]
