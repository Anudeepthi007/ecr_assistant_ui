"""Test fixtures: a private copy of the CSV data files for every test worker."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Before app modules import: point the app at a throwaway copy of backend/data, so
# tests that create records never touch the real CSV files. One copy per xdist
# worker; values are assigned, not setdefault, because workers inherit the
# controller's environment.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "main")
_ROOT = Path(tempfile.gettempdir()) / f"ecr_test_{_WORKER}"
shutil.rmtree(_ROOT, ignore_errors=True)
shutil.copytree(Path(__file__).resolve().parents[2] / "data", _ROOT / "data")
os.environ["DATA_DIR"] = str(_ROOT / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{(_ROOT / 'working_copy.db').as_posix()}"
os.environ["EMBEDDING_CACHE_PATH"] = str(_ROOT / "embeddings.json")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["AGENT_STEP_DELAY_MS"] = "0"
os.environ["APP_ENV"] = "test"


@pytest.fixture(scope="session", autouse=True)
def database():
    from app.data.csv_store import writer
    from app.database import init_db

    init_db()
    yield
    writer.flush()


@pytest.fixture(scope="session")
def rag(database):
    from app.database import session_scope
    from app.services.rag_service import get_rag_service

    service = get_rag_service()
    with session_scope() as db:
        service.index_all(db, force=True)
    return service


@pytest.fixture(scope="session")
def client(database, rag):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(database):
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
