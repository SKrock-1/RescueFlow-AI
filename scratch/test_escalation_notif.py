"""Test escalation scenario with SMS notification dispatch."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from app.database.engine import init_db
from app.database.seed import seed_all
init_db()
seed_all()

from app.agent.agent import AgentRunner
from app.providers.base import LLMProvider, LLMResponse


class EscalationMockProvider(LLMProvider):
    def __init__(self):
        self.step = 0

    def generate(self, messages, tools=None, **kwargs):
        self.step += 1
        if self.step == 1:
            return LLMResponse(content="Inspect order", tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": {"order_id": 4}}}
            ])
        elif self.step == 2:
            return LLMResponse(content="Check delivery history", tool_calls=[
                {"id": "c2", "type": "function", "function": {"name": "get_delivery_history", "arguments": {"order_id": 4}}}
            ])
        elif self.step == 3:
            return LLMResponse(content="Escalate due to repeated failures", tool_calls=[
                {"id": "c3", "type": "function", "function": {"name": "escalate_incident", "arguments": {"order_id": 4, "reason": "Exceeded 3 consecutive failed delivery attempts per Policy Rule #4."}}}
            ])
        else:
            return LLMResponse(content="Incident escalated to senior human operations with complete audit trace.")


runner = AgentRunner(provider=EscalationMockProvider())
result = runner.resolve_incident(4)  # Incident 4 = repeated failure

print("=" * 60)
print("RESCUEFLOW AI - ESCALATION SCENARIO")
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
    print(f"  [{ch.upper()}] To: {recip} ({contact}) | Type: {ntype} | Status: {status}")
print()

print("--- EXECUTION TRACE ---")
for ev in result.trace:
    label = ev.tool_name or ev.summary
    print(f"  Step {ev.step_number} [{ev.event_type:12s}] {label}")

print()
print("VERIFICATION: PASS" if result.status == "ESCALATED" and len(result.notifications) > 0 else "VERIFICATION: FAIL")
