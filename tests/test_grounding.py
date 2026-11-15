"""
RescueFlow AI — Memory and grounding tests (Phase 3).

Covers the policy corpus index, retrieval quality (recall@5), the memory
manager's ADD / UPDATE / NOOP lifecycle, past-case recall, and that every
multi-agent decision cites sources that exist.
"""

from __future__ import annotations

import json

from app.database.engine import get_db
from app.database.models import AgentMemory, KnowledgeChunk, MemoryItem
from app.grounding.evaluate import evaluate_retrieval
from app.grounding.knowledge import cited_ids, ingest, parse_corpus, search_knowledge
from app.grounding.memory import (
    active_fact,
    import_legacy,
    record_episode,
    remember_fact,
    search_customer_memory,
    search_similar_cases,
)
from app.multi_agent import roles
from app.multi_agent.workflow import MultiAgentRescue
from app.providers.base import LLMProvider, LLMResponse
from app.providers.mock_provider import MockProvider
from app.services.rescue_view import sources_for
from app.tools.knowledge_tools import search_policies


# ── Corpus and index ──
def test_corpus_chunks_have_unique_citation_ids():
    chunks = parse_corpus()
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) >= 20
    assert len(ids) == len(set(ids))
    assert "reattempt-policy#attempt-limit" in ids


def test_ingest_is_incremental(tmp_path):
    (tmp_path / "policy.md").write_text("# P\n\n## Rule one\nAlways call first.\n\n## Rule two\nNever at night.\n")
    assert ingest(tmp_path) == {"chunks": 2, "added": 2, "updated": 0, "removed": 0}
    assert ingest(tmp_path) == {"chunks": 2, "added": 0, "updated": 0, "removed": 0}
    (tmp_path / "policy.md").write_text("# P\n\n## Rule one\nAlways call twice.\n")
    assert ingest(tmp_path) == {"chunks": 1, "added": 0, "updated": 1, "removed": 1}


def test_retrieval_recall_at_5():
    result = evaluate_retrieval()
    assert result.recall_at_5 >= 0.9, result.misses
    assert result.mrr >= 0.6


def test_policy_search_tool_for_single_agent_engines():
    out = search_policies("third failed delivery attempt")
    assert out["success"] is True
    assert out["results"][0]["id"] == "reattempt-policy#attempt-limit"


# ── Memory lifecycle ──
def test_keyed_fact_add_noop_update():
    first = remember_fact(1, "Prefers morning deliveries.", key="preferred_window")
    same = remember_fact(1, "prefers morning deliveries.", key="preferred_window")
    newer = remember_fact(1, "Prefers evening deliveries.", key="preferred_window")

    assert first.action == "ADD"
    assert same.action == "NOOP" and same.memory_id == first.memory_id
    assert newer.action == "UPDATE" and newer.replaced == "Prefers morning deliveries."
    assert active_fact(1, "preferred_window").content == "Prefers evening deliveries."
    with get_db() as db:
        old = db.query(MemoryItem).filter(MemoryItem.id == first.memory_id).first()
        assert old.active is False and old.superseded_by_id == newer.memory_id


def test_stale_facts_are_not_retrieved():
    remember_fact(1, "Prefers morning deliveries.", key="preferred_window")
    remember_fact(1, "Prefers evening deliveries.", key="preferred_window")
    texts = [h.text for h in search_customer_memory(1, "preferred delivery window", k=10)]
    assert "Prefers evening deliveries." in texts
    assert "Prefers morning deliveries." not in texts


def test_near_duplicate_unkeyed_fact_is_skipped():
    remember_fact(2, "Ring the doorbell twice and wait.")
    again = remember_fact(2, "Ring the doorbell twice and wait")
    assert again.action == "NOOP"


def test_legacy_memories_are_imported_once():
    with get_db() as db:
        legacy = db.query(AgentMemory).filter(AgentMemory.customer_id == 1).count()
    assert import_legacy(1) == legacy
    assert import_legacy(1) == 0


def test_similar_cases_across_customers():
    record_episode(3, 101, "Order X: customer unavailable at office reception. Rescheduled to morning. RESOLVED.")
    record_episode(4, 102, "Order Y: COD customer had no cash. Escalated to finance. ESCALATED.")
    hits = search_similar_cases("customer was not home at the office", k=1)
    assert hits and hits[0].meta["incident_id"] == 101


# ── Grounded multi-agent decisions ──
def test_every_decision_cites_existing_sources():
    result = MultiAgentRescue(provider=MockProvider()).resolve_incident(1, plan_only=True)
    ids = cited_ids(result.decision_summary)
    assert ids, result.decision_summary
    assert all(s["title"] != "Unknown source" for s in sources_for(result.decision_summary))


def test_finished_rescue_becomes_a_past_case_for_the_next_one():
    MultiAgentRescue(provider=MockProvider()).resolve_incident(2)  # autonomous, RESOLVED
    with get_db() as db:
        assert db.query(MemoryItem).filter(MemoryItem.kind == "episodic", MemoryItem.source_incident_id == 2).count() == 1
    result = MultiAgentRescue(provider=MockProvider()).resolve_incident(1, plan_only=True)
    knowledge = next(e for e in result.trace if e.event_type == "agent" and e.tool_name == "knowledge")
    assert any(c["id"].startswith("memory:") for c in knowledge.result["similar_cases"])


def test_memory_writer_records_customer_facts():
    result = MultiAgentRescue(provider=MockProvider()).resolve_incident(1, plan_only=True)
    writer = next(e for e in result.trace if e.tool_name == "memory")
    actions = {c["action"] for c in writer.result["changes"]}
    assert actions <= {"ADD", "UPDATE", "NOOP"} and writer.result["changes"]
    assert active_fact(1, "preferred_window") is not None


def test_uncited_plan_gets_sources_attached():
    class NoCitations(LLMProvider):
        def __init__(self):
            self.base = roles.RoleAwareMockProvider()

        def generate(self, messages, tools=None, **kwargs):
            system = next(m["content"] for m in messages if m["role"] == "system")
            if "ROLE: PLANNER" in system:
                facts = roles._facts_from(messages)
                slot = facts["logistics"]["candidate_slots"][0]
                return LLMResponse(content=json.dumps({
                    "tool_name": "reschedule_delivery",
                    "arguments": {"date": slot["date"], "start_time": slot["start_time"], "end_time": slot["end_time"]},
                    "rationale": "First available slot."}))
            return self.base.generate(messages, tools, **kwargs)

    result = MultiAgentRescue(provider=NoCitations()).resolve_incident(1, plan_only=True)
    assert cited_ids(result.decision_summary)
    assert any("attached the top policy sources" in e.summary for e in result.trace if e.tool_name == "planner")


def test_index_is_built_lazily():
    with get_db() as db:
        db.query(KnowledgeChunk).delete()
    assert search_knowledge("customer not home")
