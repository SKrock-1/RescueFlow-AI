"""
RescueFlow AI — End-to-End Agent Integration Tests.

Validates:
1. Scenario 1: Multi-step investigation -> Morning slot reschedule -> Verification
2. Scenario 2: Preferred slot unavailable -> Alternative chosen
3. Scenario 3: 3 failed attempts -> Autonomous escalation with memory
4. Safety & Guards: Max steps termination, invalid tool handling
"""

import pytest
from app.agent.agent import AgentRunner
from app.agent.state import AgentStatus, AgentState
from app.providers.base import LLMProvider, LLMResponse
from app.database.engine import get_db
from app.database.models import Incident, Delivery, AgentMemory


def test_scenario_1_autonomous_reschedule(setup_test_db):
    """Scenario 1: Customer unavailable -> Autonomous Reschedule to morning slot."""
    class MultiStepProvider(LLMProvider):
        def __init__(self):
            self.step = 0

        def generate(self, messages, tools=None, **kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(
                    content="Investigating order.",
                    tool_calls=[{"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": {"order_id": 1}}}],
                )
            elif self.step == 2:
                return LLMResponse(
                    content="Inspecting customer profile.",
                    tool_calls=[{"id": "c2", "type": "function", "function": {"name": "get_customer_profile", "arguments": {"customer_id": 1}}}],
                )
            elif self.step == 3:
                return LLMResponse(
                    content="Finding available delivery slots.",
                    tool_calls=[{"id": "c3", "type": "function", "function": {"name": "find_available_delivery_slots", "arguments": {"customer_id": 1, "date": "2026-09-14"}}}],
                )
            elif self.step == 4:
                return LLMResponse(
                    content="Rescheduling to morning window 09:00-12:00.",
                    tool_calls=[{"id": "c4", "type": "function", "function": {
                        "name": "reschedule_delivery",
                        "arguments": {"order_id": 1, "date": "2026-09-14", "start_time": "09:00", "end_time": "12:00"}
                    }}],
                )
            else:
                return LLMResponse(
                    content="Delivery successfully rescheduled for 2026-09-14 09:00-12:00 according to customer morning preference."
                )

    runner = AgentRunner(provider=MultiStepProvider())
    result = runner.resolve_incident(1)

    assert result.status == "RESOLVED"
    assert result.action_taken == "reschedule_delivery"
    assert len(result.trace) >= 4
    assert len(result.candidate_actions) > 0
    assert result.candidate_actions[0].score > 0

    # Verify database mutation
    with get_db() as db:
        deliv = db.query(Delivery).filter(Delivery.order_id == 1).first()
        assert deliv.status == "RESCHEDULED"
        assert str(deliv.scheduled_date) == "2026-09-14"


def test_scenario_2_alternative_slot_reschedule(setup_test_db):
    """Scenario 2: Preferred slot unavailable -> Reschedules to afternoon alternative."""
    class AlternativeSlotProvider(LLMProvider):
        def __init__(self):
            self.step = 0

        def generate(self, messages, tools=None, **kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(
                    content="Checking slots.",
                    tool_calls=[{"id": "c1", "type": "function", "function": {"name": "find_available_delivery_slots", "arguments": {"customer_id": 2, "date": "2026-09-14"}}}],
                )
            elif self.step == 2:
                return LLMResponse(
                    content="Morning full. Rescheduling to afternoon slot 13:00-16:00.",
                    tool_calls=[{"id": "c2", "type": "function", "function": {
                        "name": "reschedule_delivery",
                        "arguments": {"order_id": 2, "date": "2026-09-14", "start_time": "13:00", "end_time": "16:00"}
                    }}],
                )
            else:
                return LLMResponse(
                    content="Rescheduled to afternoon 13:00-16:00 because morning slot was unavailable."
                )

    runner = AgentRunner(provider=AlternativeSlotProvider())
    result = runner.resolve_incident(2)

    assert result.status == "RESOLVED"
    assert "afternoon" in result.decision_summary.lower()


def test_scenario_3_repeated_failure_escalation(setup_test_db):
    """Scenario 3: Repeated failure (3 attempts) -> Agent retrieves history and escalates."""
    class EscalationProvider(LLMProvider):
        def __init__(self):
            self.step = 0

        def generate(self, messages, tools=None, **kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(
                    content="Checking delivery history for order 4.",
                    tool_calls=[{"id": "c1", "type": "function", "function": {"name": "get_delivery_history", "arguments": {"order_id": 4}}}],
                )
            elif self.step == 2:
                return LLMResponse(
                    content="3 attempts failed. Escalating per Policy Rule #4.",
                    tool_calls=[{"id": "c2", "type": "function", "function": {
                        "name": "escalate_incident",
                        "arguments": {"order_id": 4, "reason": "3 consecutive failed attempts. Customer unavailable repeatedly."}
                    }}],
                )
            else:
                return LLMResponse(
                    content="Incident escalated to supervisor due to 3 consecutive delivery failures."
                )

    runner = AgentRunner(provider=EscalationProvider())
    result = runner.resolve_incident(4)

    assert result.status == "ESCALATED"
    assert result.action_taken == "escalate_incident"

    # Verify incident and order escalated in database
    with get_db() as db:
        inc = db.query(Incident).filter(Incident.id == 4).first()
        assert inc.status == "ESCALATED"


def test_agent_max_steps_termination(setup_test_db):
    """Ensure agent safely terminates and does not loop forever when max_steps is reached."""
    class InfiniteLoopProvider(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            # Keeps asking to get_order indefinitely
            return LLMResponse(
                content="Looping call.",
                tool_calls=[{"id": "loop", "type": "function", "function": {"name": "get_order", "arguments": {"order_id": 1}}}],
            )

    runner = AgentRunner(provider=InfiniteLoopProvider(), max_steps=3)
    result = runner.resolve_incident(1)

    assert result.status == "FAILED"
    assert "exceeded maximum iteration limit" in result.decision_summary.lower()


def test_invalid_tool_call_handled_gracefully(setup_test_db):
    """Ensure agent handles invalid/hallucinated tool names without crashing."""
    class HallucinatedToolProvider(LLMProvider):
        def __init__(self):
            self.step = 0

        def generate(self, messages, tools=None, **kwargs):
            self.step += 1
            if self.step == 1:
                return LLMResponse(
                    content="Calling nonexistent tool.",
                    tool_calls=[{"id": "bad", "type": "function", "function": {"name": "teleport_package_now", "arguments": {}}}],
                )
            else:
                return LLMResponse(content="Recovered from invalid tool call. Escalating.")

    runner = AgentRunner(provider=HallucinatedToolProvider())
    result = runner.resolve_incident(1)

    # Agent records error but continues loop and terminates gracefully
    assert any("Unknown tool" in err for err in result.errors)
