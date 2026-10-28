"""
RescueFlow AI — Agent Observer & Callback System.

Allows external consumers (CLI, Streamlit, WebSockets) to subscribe
to real-time agent execution events as they happen.
"""

from __future__ import annotations

from typing import Callable, Protocol
from app.schemas.models import TraceEvent


class AgentObserver(Protocol):
    """Protocol for receiving real-time agent execution events."""

    def on_step(self, event: TraceEvent) -> None:
        """Called immediately after an event is recorded in the trace."""
        ...


class ConsoleProgressObserver:
    """Prints colored real-time step updates to stdout."""

    _COLORS = {
        "observation": "\033[94m",  # Blue
        "tool_call": "\033[93m",    # Yellow
        "decision": "\033[92m",     # Green
        "error": "\033[91m",        # Red
        "reset": "\033[0m",
    }

    def on_step(self, event: TraceEvent) -> None:
        color = self._COLORS.get(event.event_type, self._COLORS["reset"])
        reset = self._COLORS["reset"]
        prefix = f"{color}[Step {event.step_number} | {event.event_type.upper()}]{reset}"

        if event.tool_name:
            print(f"  {prefix} Tool: \033[1m{event.tool_name}\033[0m - {event.summary}")
        else:
            print(f"  {prefix} {event.summary}")
