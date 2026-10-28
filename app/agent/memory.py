"""
RescueFlow AI — Persistent Memory System.

Stores and retrieves operational memory about customers and incidents.
Allows past resolutions, preferences, and repeated failures to visibly
influence future agent reasoning and decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.database.engine import get_db
from app.database.models import AgentMemory

logger = logging.getLogger(__name__)


def load_customer_memory(customer_id: int) -> list[dict[str, Any]]:
    """Load all memory entries for a specific customer.

    Returns:
        List of dicts containing memory_type, content, importance, created_at.
    """
    with get_db() as db:
        memories = (
            db.query(AgentMemory)
            .filter(AgentMemory.customer_id == customer_id)
            .order_by(AgentMemory.importance.desc(), AgentMemory.created_at.desc())
            .all()
        )

        return [
            {
                "id": m.id,
                "customer_id": m.customer_id,
                "memory_type": m.memory_type,
                "content": m.content,
                "importance": m.importance,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ]


def save_memory(
    customer_id: int,
    memory_type: str,
    content: str,
    importance: float = 0.5,
) -> dict[str, Any]:
    """Persist a new memory entry for a customer.

    Args:
        customer_id: The customer ID.
        memory_type: 'preference' | 'resolution' | 'escalation' | 'observation'.
        content: Factual description of the event or preference.
        importance: Numerical score 0.0 to 1.0.

    Returns:
        Dict of the saved memory record.
    """
    with get_db() as db:
        mem = AgentMemory(
            customer_id=customer_id,
            memory_type=memory_type,
            content=content,
            importance=min(max(importance, 0.0), 1.0),
            created_at=datetime.now(timezone.utc),
        )
        db.add(mem)
        db.flush()

        logger.info(
            "Saved memory for customer %d [type=%s, importance=%.2f]: %s",
            customer_id, memory_type, importance, content[:60]
        )

        return {
            "id": mem.id,
            "customer_id": mem.customer_id,
            "memory_type": mem.memory_type,
            "content": mem.content,
            "importance": mem.importance,
            "created_at": mem.created_at.isoformat(),
        }


def summarize_relevant_memory(customer_id: int, incident_type: str | None = None) -> str:
    """Produce a concise, contextual summary of customer memory for LLM context.

    Filters and prioritizes memory facts relevant to the ongoing delivery incident.
    """
    memories = load_customer_memory(customer_id)
    if not memories:
        return "No prior operational memory recorded for this customer."

    lines: list[str] = [f"Persistent Memory for Customer #{customer_id}:"]
    for m in memories:
        m_type = m["memory_type"].upper()
        content = m["content"]
        importance = m["importance"]
        lines.append(f"- [{m_type}] (weight: {importance:.2f}): {content}")

    return "\n".join(lines)
