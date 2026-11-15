"""
RescueFlow AI — Knowledge Tools.

Read-only tool that lets single-agent engines ground their decisions in the
delivery policies (the multi-agent workflow's Knowledge agent uses the same
search directly).
"""

from __future__ import annotations

from typing import Any

from app.tools.registry import registry


def search_policies(query: str) -> dict[str, Any]:
    """Search the delivery operating procedures and return the most relevant sections.

    query: What you need to know, e.g. "customer not home reschedule" or "third failed attempt".
    """
    from app.grounding.knowledge import search_knowledge

    hits = search_knowledge(query, k=3)
    return {
        "success": True,
        "query": query,
        "results": [{"id": h.id, "title": h.title, "text": h.text} for h in hits],
        "note": "Cite the id of any policy you rely on in square brackets, e.g. [reattempt-policy#attempt-limit].",
    }


registry.register(search_policies, mutation=False)
