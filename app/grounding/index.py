"""
RescueFlow AI — Hybrid retrieval (BM25 keywords + vector similarity).

Both rankings are combined with reciprocal rank fusion, so a passage that is
strong on either signal surfaces. Works on SQLite and Postgres through
SQLAlchemy; vectors are stored as JSON and scored in Python, which is fast
for a corpus of this size (hundreds of chunks). On a Postgres deployment the
same tables can move to a pgvector column without changing callers.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from typing import Iterable

from app.grounding.embeddings import cosine, get_embedder
from app.grounding.text import tokenize

RRF_K = 60


@dataclass
class Hit:
    id: str            # citation ID: "<file>#<section>" or "memory:<n>"
    title: str
    text: str
    score: float
    kind: str          # sop | semantic | episodic
    meta: dict


@dataclass
class Doc:
    id: str
    title: str
    text: str
    kind: str
    embedding: list[float]
    meta: dict


def _bm25_scores(query_tokens: list[str], docs: list[Doc], k1: float = 1.4, b: float = 0.75) -> list[float]:
    tokenized = [tokenize(f"{d.title} {d.text}") for d in docs]
    n = len(docs)
    avg_len = (sum(len(t) for t in tokenized) / n) if n else 0.0
    df = Counter()
    for toks in tokenized:
        df.update(set(toks))
    scores = []
    for toks in tokenized:
        tf = Counter(toks)
        score = 0.0
        for q in set(query_tokens):
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            denom = tf[q] + k1 * (1 - b + b * len(toks) / (avg_len or 1))
            score += idf * tf[q] * (k1 + 1) / denom
        scores.append(score)
    return scores


def hybrid_search(query: str, docs: Iterable[Doc], k: int = 5) -> list[Hit]:
    docs = list(docs)
    if not docs or not (query or "").strip():
        return []
    q_tokens = tokenize(query)
    q_vec = get_embedder().embed([query])[0]
    bm25 = _bm25_scores(q_tokens, docs)
    dense = [cosine(q_vec, d.embedding) for d in docs]

    def ranks(values: list[float]) -> dict[int, int]:
        order = sorted((i for i, v in enumerate(values) if v > 0), key=lambda i: -values[i])
        return {i: r for r, i in enumerate(order)}

    r_bm25, r_dense = ranks(bm25), ranks(dense)
    fused = {}
    for i in set(r_bm25) | set(r_dense):
        fused[i] = sum(1.0 / (RRF_K + 1 + r[i]) for r in (r_bm25, r_dense) if i in r)
    best = sorted(fused, key=lambda i: -fused[i])[:k]
    return [
        Hit(id=docs[i].id, title=docs[i].title, text=docs[i].text, score=round(fused[i], 5),
            kind=docs[i].kind, meta=docs[i].meta)
        for i in best
    ]


def load_embedding(raw: str) -> list[float]:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
