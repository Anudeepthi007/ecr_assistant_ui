"""``python -m app.seed`` - check that the CSV data files load, and build embeddings.

    python -m app.seed                    load backend/data/*.csv and print row counts
    python -m app.seed --index            also build the embedding cache (reuses unchanged rows)
    python -m app.seed --index --force    re-embed every row

It loads into a private in-memory copy, so it is safe to run while the backend
is up, and it never changes the CSV files.
"""
from __future__ import annotations

import os
import sys

# Before any app import: keep this check away from the running backend's working copy.
os.environ["DATABASE_URL"] = "sqlite://"

from app.config import settings  # noqa: E402
from app.data.csv_store import CsvDataError  # noqa: E402
from app.database import init_db, session_scope  # noqa: E402
from app.logging import configure_logging  # noqa: E402


def main() -> int:
    configure_logging()
    try:
        counts = init_db()
    except CsvDataError as exc:
        print(f"CSV data error: {exc}")
        return 1
    print(f"Loaded from {settings.data_dir}:")
    for table, rows in counts.items():
        print(f"  {table:<16} {rows:>5}")

    if "--index" in sys.argv:
        from app.services.rag_service import get_rag_service

        with session_scope() as db:
            print("Indexed:", get_rag_service().index_all(db, force="--force" in sys.argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
