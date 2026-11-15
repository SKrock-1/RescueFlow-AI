"""
RescueFlow AI — Text embeddings for retrieval.

Default: ``HashingEmbedder``, a dependency-free embedder (signed feature
hashing of words and word pairs). It needs no model download, gives the same
vector on every machine, and pairs with BM25 keyword search in the hybrid
index. Set ``EMBEDDINGS_BACKEND=fastembed`` to use a neural model (BAAI
bge-small) when the ``fastembed`` package is installed; it downloads the model
on first use.
"""

from __future__ import annotations

import logging
import math
import zlib
from functools import lru_cache
from typing import Protocol

from app.grounding.text import tokenize

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feat in features:
            h = zlib.crc32(feat.encode("utf-8"))
            index = h % self.dim
            sign = 1.0 if (h >> 31) & 1 else -1.0
            vec[index] += sign * (1.5 if "_" in feat else 1.0)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class FastEmbedEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding  # optional dependency

        self._model = TextEmbedding(model_name=model_name)
        self.name = f"fastembed:{model_name}"
        self.dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    from app.config import get_settings

    backend = (get_settings().embeddings_backend or "hashing").lower()
    if backend == "fastembed":
        try:
            return FastEmbedEmbedder()
        except Exception as exc:  # missing package or no network for the model
            logger.warning("fastembed unavailable (%s); using the hashing embedder.", exc)
    return HashingEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
