"""Quick integration test for notification dispatch."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.database.engine import init_db
from app.database.seed import seed_all
init_db()
seed_all()

from app.agent.agent import AgentRunner
from app.providers.base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    def __init__(self):
        self.step = 0

    def generate(self, messages, tools=None, **kwargs):
        self.step += 1
        if self.step == 1:
            return LLMResponse(content="Inspect order", tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": {"order_id": 1}}}
            ])
        elif self.step == 2:
            return LLMResponse(content="Check profile", tool_calls=[
                {"id": "c2", "type": "function", "function": {"name": "get_customer_profile", "arguments": {"customer_id": 1}}}
            ])
        elif self.step == 3:
            return LLMResponse(content="Find slots", tool_calls=[
                {"id": "c3", "type": "function", "function": {"name": "find_available_delivery_slots", "arguments": {"customer_id": 1, "date": "2026-09-15"}}}
            ])
        elif self.step == 4:
            return LLMResponse(content="Reschedule", tool_calls=[
                {"id": "c4", "type": "function", "function": {"name": "reschedule_delivery", "arguments": {"order_id": 1, "date": "2026-09-15", "start_time": "09:00", "end_time": "12:00"}}}
            ])
        else:
            return LLMResponse(content="Delivery rescheduled to morning slot matching customer preference.")


runner = AgentRunner(provider=MockProvider())
result = runner.resolve_incident(1)

print("=" * 60)
print("RESCUEFLOW AI - AGENT RESULT")
print("=" * 60)
print(f"Status:   {result.status}")
print(f"Action:   {result.action_taken}")
print(f"Decision: {result.decision_summary}")
print()

print("--- NOTIFICATIONS DISPATCHED ---")
print(f"Count: {len(result.notifications)}")
for n in result.notifications:
    ch = n.get("channel", "N/A")
    recip = n.get("recipient", "N/A")
    contact = n.get("contact", "N/A")
    ntype = n.get("type", "N/A")
    status = n.get("status", "N/A")
    preview = n.get("message_preview", "")
    print(f"  [{ch.upper()}] To: {recip} ({contact}) | Type: {ntype} | Status: {status}")
    print(f"    Preview: {preview}")
print()

print("--- MEMORY UPDATES ---")
for m in result.memory_updates:
    print(f"  * {m}")
print()

print("--- EXECUTION TRACE ---")
print(f"Total Events: {len(result.trace)}")
for ev in result.trace:
    label = ev.tool_name or ev.summary
    print(f"  Step {ev.step_number} [{ev.event_type:12s}] {label}")

print()
print("VERIFICATION: PASS" if result.status == "RESOLVED" and len(result.notifications) > 0 else "VERIFICATION: FAIL")
