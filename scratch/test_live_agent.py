import sys
from pathlib import Path

# Force UTF-8 stdout for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.seed import seed_all
from app.agent.agent import AgentRunner
from app.providers.groq_provider import GroqProvider
from app.providers.nvidia_provider import NvidiaProvider
from app.config import get_settings

def run_live():
    # 1. Fresh seed
    print("=== [1] Reseeding database ===")
    seed_all()

    settings = get_settings()
    print(f"\nConfigured Provider: {settings.llm_provider}")
    print(f"Groq Model: {settings.groq_model}")
    print(f"NVIDIA Model: {settings.nvidia_model}")

    # 2. Run Groq on Incident 1 (Customer Unavailable)
    print("\n" + "="*50)
    print("=== [2] Testing Live Groq Provider on Incident #1 ===")
    print("="*50)
    groq_provider = GroqProvider()
    groq_runner = AgentRunner(provider=groq_provider)

    res1 = groq_runner.resolve_incident(1)
    print(f"\n>>> GROQ RESOLUTION STATUS: {res1.status}")
    print(f">>> ACTION TAKEN: {res1.action_taken}")
    print(f">>> DECISION SUMMARY:\n{res1.decision_summary}")
    print(f"\n>>> EXECUTION TRACE ({len(res1.trace)} events):")
    for ev in res1.trace:
        print(f"  Step {ev.step_number} [{ev.event_type}]: {ev.tool_name or ''} - {ev.summary}")

if __name__ == "__main__":
    run_live()
