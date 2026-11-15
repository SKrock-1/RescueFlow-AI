"""
RescueFlow AI — Long-term memory manager.

Follows Mem0's memory lifecycle without its dependencies: each new fact is
compared with what is already stored and becomes ADD, UPDATE or NOOP.

- Semantic memory: facts about a customer. A fact with a ``key`` (for
  example ``preferred_window``) has one active version; a different value
  UPDATEs it and the old version is kept, inactive, for audit. A fact without
  a key is skipped (NOOP) when a near-identical active fact exists.
- Episodic memory: one record per finished rescue (what failed, what was
  done, how it ended), searchable across customers for "similar cases".

Search is hybrid (BM25 + vectors). Citation IDs are ``memory:<id>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging

from app.database.engine import get_db
from app.database.models import AgentMemory, MemoryItem
from app.grounding.embeddings import cosine, get_embedder
from app.grounding.index import Doc, Hit, hybrid_search, load_embedding

logger = logging.getLogger(__name__)

FACT_KEYS = {"preferred_window", "delivery_instructions", "address_note", "contact_preference",
             "availability_note", "customer_request", "vip_status"}
DUPLICATE_SIMILARITY = 0.9


@dataclass
class MemoryChange:
    action: str          # ADD | UPDATE | NOOP
    memory_id: int
    content: str
    replaced: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _embed(text: str) -> str:
    return json.dumps(get_embedder().embed([text])[0])


def remember_fact(customer_id: int, content: str, key: str | None = None, importance: float = 0.7,
                  source: str = "agent", incident_id: int | None = None) -> MemoryChange:
    """Store a customer fact, updating or skipping it when memory already has it."""
    content = content.strip()
    key = key if key in FACT_KEYS else None
    with get_db() as db:
        active = db.query(MemoryItem).filter(
            MemoryItem.customer_id == customer_id, MemoryItem.kind == "semantic", MemoryItem.active.is_(True)
        )
        if key:
            current = active.filter(MemoryItem.key == key).order_by(MemoryItem.id.desc()).first()
            if current and current.content.strip().lower() == content.lower():
                current.updated_at = _now()
                return MemoryChange("NOOP", current.id, content)
        else:
            current = None
            vec = get_embedder().embed([content])[0]
            for item in active.filter(MemoryItem.key.is_(None)).all():
                if cosine(vec, load_embedding(item.embedding)) >= DUPLICATE_SIMILARITY:
                    item.updated_at = _now()
                    return MemoryChange("NOOP", item.id, content)

        new = MemoryItem(
            customer_id=customer_id, kind="semantic", key=key, content=content, importance=importance,
            source=source, source_incident_id=incident_id, embedding=_embed(content),
        )
        db.add(new)
        db.flush()
        if current:
            current.active = False
            current.superseded_by_id = new.id
            current.updated_at = _now()
            return MemoryChange("UPDATE", new.id, content, replaced=current.content)
        return MemoryChange("ADD", new.id, content)


def record_episode(customer_id: int, incident_id: int, text: str, importance: float = 0.8) -> int:
    """Store one finished rescue as an episodic memory (one per incident)."""
    with get_db() as db:
        existing = db.query(MemoryItem).filter(
            MemoryItem.kind == "episodic", MemoryItem.source_incident_id == incident_id
        ).first()
        if existing:
            existing.content, existing.embedding, existing.updated_at = text, _embed(text), _now()
            return existing.id
        item = MemoryItem(customer_id=customer_id, kind="episodic", content=text, importance=importance,
                          source="agent", source_incident_id=incident_id, embedding=_embed(text))
        db.add(item)
        db.flush()
        return item.id


def import_legacy(customer_id: int) -> int:
    """Copy the older AgentMemory rows (seed data, Shopify sync) into memory once."""
    count = 0
    with get_db() as db:
        done = {
            m.source for m in db.query(MemoryItem.source).filter(
                MemoryItem.customer_id == customer_id, MemoryItem.source.like("legacy:%")
            ).all()
        }
        rows = db.query(AgentMemory).filter(AgentMemory.customer_id == customer_id).all()
    for row in rows:
        if f"legacy:{row.id}" in done:
            continue
        kind = "episodic" if row.memory_type in {"resolution", "escalation"} else "semantic"
        with get_db() as db:
            db.add(MemoryItem(
                customer_id=customer_id, kind=kind, content=row.content, importance=row.importance,
                source=f"legacy:{row.id}", embedding=_embed(row.content),
            ))
        count += 1
    return count


def _docs(query_filter) -> list[Doc]:
    with get_db() as db:
        rows = query_filter(db.query(MemoryItem)).all()
        return [
            Doc(id=f"memory:{r.id}", title=f"{r.kind} memory", text=r.content, kind=r.kind,
                embedding=load_embedding(r.embedding),
                meta={"customer_id": r.customer_id, "key": r.key, "incident_id": r.source_incident_id,
                      "importance": r.importance})
            for r in rows
        ]


def search_customer_memory(customer_id: int, query: str, k: int = 4) -> list[Hit]:
    """Active facts and past episodes for one customer, most relevant first."""
    import_legacy(customer_id)
    return hybrid_search(query, _docs(lambda q: q.filter(
        MemoryItem.customer_id == customer_id, MemoryItem.active.is_(True))), k=k)


def search_similar_cases(query: str, exclude_incident_id: int | None = None, k: int = 3) -> list[Hit]:
    """Past rescues of any customer that look like this one (case-based reasoning)."""
    def flt(q):
        q = q.filter(MemoryItem.kind == "episodic", MemoryItem.active.is_(True),
                     MemoryItem.source_incident_id.isnot(None))
        if exclude_incident_id:
            q = q.filter(MemoryItem.source_incident_id != exclude_incident_id)
        return q
    return hybrid_search(query, _docs(flt), k=k)


def active_fact(customer_id: int, key: str) -> MemoryItem | None:
    with get_db() as db:
        return db.query(MemoryItem).filter(
            MemoryItem.customer_id == customer_id, MemoryItem.key == key, MemoryItem.active.is_(True)
        ).order_by(MemoryItem.id.desc()).first()
