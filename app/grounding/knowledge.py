"""
RescueFlow AI — The SOP knowledge corpus: ingestion and search.

``knowledge/*.md`` is split into one chunk per ``##`` section. Each chunk has
a stable citation ID ``<file>#<section-slug>``. The index rebuilds itself when
a file changes, so editing a policy and running a rescue is enough.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app.database.engine import get_db
from app.database.models import KnowledgeChunk
from app.grounding.embeddings import get_embedder
from app.grounding.index import Doc, Hit, hybrid_search, load_embedding
from app.grounding.text import slugify

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
CITATION = re.compile(r"\[([a-z0-9\-]+#[a-z0-9\-]+|memory:\d+)\]")


def parse_corpus(directory: Path = KNOWLEDGE_DIR) -> list[dict]:
    """Split every markdown file (except README) into ## sections."""
    chunks = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        doc_title = path.stem.replace("-", " ").title()
        current, lines = None, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# ") and current is None:
                doc_title = line[2:].strip()
            elif line.startswith("## "):
                if current:
                    chunks.append((path.stem, doc_title, current, "\n".join(lines).strip()))
                current, lines = line[3:].strip(), []
            elif current is not None:
                lines.append(line)
        if current:
            chunks.append((path.stem, doc_title, current, "\n".join(lines).strip()))
    return [
        {"chunk_id": f"{stem}#{slugify(section)}", "source": stem,
         "title": f"{doc_title}: {section}", "content": body}
        for stem, doc_title, section, body in chunks if body
    ]


def _hash(chunk: dict) -> str:
    return hashlib.sha256(f"{get_embedder().name}|{chunk['title']}|{chunk['content']}".encode()).hexdigest()


def ingest(directory: Path = KNOWLEDGE_DIR) -> dict[str, int]:
    """Upsert changed chunks, remove deleted ones. Returns counts."""
    chunks = parse_corpus(directory)
    wanted = {c["chunk_id"]: c for c in chunks}
    added = updated = removed = 0
    with get_db() as db:
        existing = {row.chunk_id: row for row in db.query(KnowledgeChunk).all()}
        stale = [c for cid, c in wanted.items() if cid not in existing or existing[cid].content_hash != _hash(c)]
        vectors = get_embedder().embed([f"{c['title']}. {c['content']}" for c in stale]) if stale else []
        for chunk, vec in zip(stale, vectors):
            row = existing.get(chunk["chunk_id"])
            if row is None:
                row = KnowledgeChunk(chunk_id=chunk["chunk_id"])
                db.add(row)
                added += 1
            else:
                updated += 1
            row.source, row.title, row.content = chunk["source"], chunk["title"], chunk["content"]
            row.embedding = json.dumps(vec)
            row.content_hash = _hash(chunk)
            row.updated_at = datetime.now(timezone.utc)
        for cid, row in existing.items():
            if cid not in wanted:
                db.delete(row)
                removed += 1
    return {"chunks": len(wanted), "added": added, "updated": updated, "removed": removed}


_checked = False


def ensure_index() -> None:
    """Build or refresh the index once per process (cheap when nothing changed)."""
    global _checked
    with get_db() as db:
        empty = db.query(KnowledgeChunk).count() == 0
    if empty or not _checked:
        result = ingest()
        _checked = True
        if result["added"] or result["updated"] or result["removed"]:
            logger.info("Knowledge index refreshed: %s", result)


def search_knowledge(query: str, k: int = 4) -> list[Hit]:
    ensure_index()
    with get_db() as db:
        docs = [
            Doc(id=r.chunk_id, title=r.title, text=r.content, kind="sop",
                embedding=load_embedding(r.embedding), meta={"source": r.source})
            for r in db.query(KnowledgeChunk).all()
        ]
    return hybrid_search(query, docs, k=k)


def get_chunks(ids: list[str]) -> dict[str, KnowledgeChunk]:
    if not ids:
        return {}
    with get_db() as db:
        return {r.chunk_id: r for r in db.query(KnowledgeChunk).filter(KnowledgeChunk.chunk_id.in_(ids)).all()}


def cited_ids(text: str) -> list[str]:
    """Citation IDs written as [id] in agent text, in order, without repeats."""
    seen: list[str] = []
    for cid in CITATION.findall(text or ""):
        if cid not in seen:
            seen.append(cid)
    return seen
