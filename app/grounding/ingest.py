"""Rebuild the knowledge index: ``python -m app.grounding.ingest``."""

from __future__ import annotations

from app.database.engine import init_db
from app.grounding.knowledge import ingest


def main() -> None:
    init_db()
    result = ingest()
    print(f"Knowledge index: {result['chunks']} chunks "
          f"({result['added']} added, {result['updated']} updated, {result['removed']} removed).")


if __name__ == "__main__":
    main()
