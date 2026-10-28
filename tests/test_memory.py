"""
RescueFlow AI — Memory System Unit Tests.

Validates memory loading, persistence, and relevance summarization.
"""

from app.agent.memory import (
    load_customer_memory,
    save_memory,
    summarize_relevant_memory,
)


def test_load_customer_memory():
    # Customer 1 has seeded memories
    memories = load_customer_memory(1)
    assert len(memories) >= 2
    types = [m["memory_type"] for m in memories]
    assert "preference" in types


def test_save_memory_persistence():
    # Save new memory
    saved = save_memory(
        customer_id=1,
        memory_type="observation",
        content="Customer answered verification call immediately.",
        importance=0.88,
    )
    assert saved["customer_id"] == 1
    assert saved["importance"] == 0.88

    # Verify loaded back
    memories = load_customer_memory(1)
    matching = [m for m in memories if "answered verification call" in m["content"]]
    assert len(matching) == 1
    assert matching[0]["importance"] == 0.88


def test_summarize_relevant_memory():
    summary = summarize_relevant_memory(1)
    assert "Customer #1" in summary
    assert "PREFERENCE" in summary
    assert len(summary) > 50

    # Non-existent customer memory
    empty_summary = summarize_relevant_memory(9999)
    assert "No prior operational memory" in empty_summary
