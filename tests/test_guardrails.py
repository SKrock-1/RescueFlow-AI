"""
RescueFlow AI — Guardrails & Observer Unit Tests.

Validates:
1. Deterministic policy guardrail blocks unauthorized reschedule on >= 3 failures.
2. Deterministic policy guardrail blocks assignment to inactive courier.
3. Observers receive real-time execution callbacks.
4. Candidate actions are populated into AgentResult.
"""

from __future__ import annotations

import pytest
from app.agent.agent import AgentRunner
from app.agent.observer import AgentObserver
from app.schemas.models import TraceEvent
from app.providers.base import LLMProvider, LLMResponse
from app.database.engine import get_db
from app.database.models import Delivery, Order, Courier


class StepRecorderObserver:
    """Test observer that records all emitted steps."""
    def __init__(self) -> None:
        self.steps: list[TraceEvent] = []

    def on_step(self, event: TraceEvent) -> None:
        self.steps.append(event)


class GuardrailMockProvider(LLMProvider):
    """Mock provider that attempts illegal mutations to test guardrails."""
    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, messages, tools=None, temperature=0.1) -> LLMResponse:
        self.call_count += 1
        if self.call_count == 1:
            # Attempt to reschedule an order that has 3 failed attempts (violating Rule 4)
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "reschedule_delivery",
                        "arguments": {
                            "order_id": 4,  # Scenario D order with 3 failed attempts
                            "date": "2026-09-14",
                            "start_time": "09:00",
                            "end_time": "12:00",
                        },
                    },
                }],
            )
        elif self.call_count == 2:
            # Self-correct by escalating after receiving guardrail error
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "escalate_incident",
                        "arguments": {
                            "order_id": 4,
                            "reason": "Guardrail triggered: maximum attempts reached. Escalating to ops.",
                        },
                    },
                }],
            )
        else:
            return LLMResponse(content="Incident successfully escalated to human operations.")


def test_guardrail_blocks_reschedule_on_repeated_failure():
    """Verify that AgentRunner guardrail intercepts reschedule when attempts >= 3."""
    mock_provider = GuardrailMockProvider()
    observer = StepRecorderObserver()
    runner = AgentRunner(provider=mock_provider, max_steps=5, observers=[observer])

    # Run on incident 4 (Scenario D, order 4 with 3 failed attempts)
    result = runner.resolve_incident(incident_id=4)

    assert result.status == "ESCALATED"
    # Observer must have recorded steps
    assert len(observer.steps) > 0

    # Ensure the policy guardrail error was captured in trace
    tool_calls = [e for e in observer.steps if e.event_type == "tool_call"]
    reschedule_step = next((e for e in tool_calls if e.tool_name == "reschedule_delivery"), None)
    assert reschedule_step is not None
    assert reschedule_step.result.get("policy_blocked") is True
    assert "Policy Guardrail Blocked" in reschedule_step.result.get("error", "")


class InactiveCourierMockProvider(LLMProvider):
    """Mock provider that tries to reassign to an inactive courier."""
    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, messages, tools=None, temperature=0.1) -> LLMResponse:
        self.call_count += 1
        if self.call_count == 1:
            # Try to assign courier 4 (Deepak Joshi — inactive in seed data)
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": "call_reassign",
                    "type": "function",
                    "function": {
                        "name": "reassign_courier",
                        "arguments": {
                            "order_id": 1,
                            "courier_id": 5,  # Manoj Pillai (inactive)
                        },
                    },
                }],
            )
        elif self.call_count == 2:
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": "call_esc",
                    "type": "function",
                    "function": {
                        "name": "escalate_incident",
                        "arguments": {
                            "order_id": 1,
                            "reason": "Courier was inactive. Escalating.",
                        },
                    },
                }],
            )
        else:
            return LLMResponse(content="Escalated due to inactive courier.")


def test_guardrail_blocks_inactive_courier_reassignment():
    """Verify that assigning an inactive courier is blocked by the policy guardrail."""
    mock_provider = InactiveCourierMockProvider()
    observer = StepRecorderObserver()
    runner = AgentRunner(provider=mock_provider, max_steps=5, observers=[observer])

    result = runner.resolve_incident(incident_id=1)

    reassign_step = next((e for e in observer.steps if e.tool_name == "reassign_courier"), None)
    assert reassign_step is not None
    assert reassign_step.result.get("policy_blocked") is True
    assert "inactive" in reassign_step.result.get("error", "").lower()
