"""
RescueFlow AI — Custom Exception Hierarchy.

Each exception maps to a specific failure mode in the agent pipeline.
"""

from __future__ import annotations


class RescueFlowError(Exception):
    """Base exception for all RescueFlow errors."""


# ── Tool Errors ──

class ToolExecutionError(RescueFlowError):
    """A tool raised an error during execution."""

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"Tool '{tool_name}' failed: {detail}")


class ToolNotFoundError(RescueFlowError):
    """LLM requested a tool that is not in the whitelist."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Unknown tool: '{tool_name}'")


class InvalidArgumentsError(RescueFlowError):
    """Tool arguments failed validation."""

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"Invalid arguments for '{tool_name}': {detail}")


# ── Agent Errors ──

class AgentMaxStepsError(RescueFlowError):
    """Agent exceeded the maximum number of iterations."""

    def __init__(self, max_steps: int) -> None:
        self.max_steps = max_steps
        super().__init__(f"Agent exceeded {max_steps} steps without resolution")


class EscalationRequired(RescueFlowError):
    """Agent determined the incident must be escalated to a human."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Escalation required: {reason}")


# ── Provider Errors ──

class ProviderError(RescueFlowError):
    """LLM provider returned an error or is unreachable."""

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"Provider '{provider}' error: {detail}")


# ── Data Errors ──

class RecordNotFoundError(RescueFlowError):
    """A required database record was not found."""

    def __init__(self, entity: str, identifier: str) -> None:
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} '{identifier}' not found")
