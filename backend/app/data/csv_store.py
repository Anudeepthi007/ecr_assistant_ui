"""CSV files are the system of record.

One CSV per table lives in ``DATA_DIR`` (``backend/data`` by default). At startup
the files are loaded into an in-memory SQL engine, so every repository, agent
tool and API route keeps using ordinary SQLAlchemy queries. Whenever a session
commits a change to a table, that table is written back to its CSV file by a
background writer, so nothing is lost on restart and the files can be edited
by hand.

Conventions
    * header row = the model's column names; ``id`` is never stored (rows are
      identified by their business key, e.g. ``ecr_id``)
    * lists and dicts are JSON text, booleans are ``true``/``false``,
      timestamps are ISO-8601
    * ``dependencies.csv`` refers to components by ``component_id``
    * a full analysis report is too large for a cell, so ``impact_reports.csv``
      stores a path and the JSON lives in ``reports/<workflow_id>.json``
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.logging import get_logger
from app.models import (
    AgentRun,
    Comment,
    Component,
    Defect,
    Dependency,
    ECR,
    Evidence,
    Feedback,
    ImpactReport,
    Requirement,
    TestCase,
    TestExecution,
)

logger = get_logger("ecr.csv")

SKIP_COLUMNS = {"id"}
SUPPRESS = "csv_suppress_write_back"
DIRTY = "csv_dirty_tables"
_MISSING = object()


class CsvDataError(ValueError):
    """A CSV file could not be loaded; the message names the file, line and column."""


@dataclass(frozen=True)
class TableSpec:
    file: str
    model: type
    required: bool = True
    # column -> relative path pattern; the cell holds the path, the file holds the JSON
    file_columns: dict[str, str] = field(default_factory=dict)

    @property
    def table(self) -> str:
        return self.model.__tablename__


# Load order matters: dependencies need components, executions need test cases.
TABLES: list[TableSpec] = [
    TableSpec("components.csv", Component),
    TableSpec("dependencies.csv", Dependency),
    TableSpec("requirements.csv", Requirement),
    TableSpec("defects.csv", Defect),
    TableSpec("test_cases.csv", TestCase),
    TableSpec("test_executions.csv", TestExecution),
    TableSpec("ecrs.csv", ECR),
    TableSpec("comments.csv", Comment),
    TableSpec("evidence.csv", Evidence),
    TableSpec(
        "impact_reports.csv",
        ImpactReport,
        required=False,
        file_columns={"report_json": "reports/{workflow_id}.json"},
    ),
    TableSpec("agent_runs.csv", AgentRun, required=False),
    TableSpec("feedback.csv", Feedback, required=False),
]
TABLE_BY_NAME = {spec.table: spec for spec in TABLES}


def data_dir() -> Path:
    return Path(settings.data_dir)


# ---------------------------------------------------------------------------
# value conversion
# ---------------------------------------------------------------------------
def _encode(column, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(column.type, JSON):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(column.type, Boolean):
        return "true" if value else "false"
    if isinstance(column.type, DateTime):
        return value.isoformat()
    return str(value)


def _decode(column, raw: str | None) -> Any:
    if raw is None or raw.strip() == "":
        return _MISSING
    kind = column.type
    if isinstance(kind, JSON):
        return json.loads(raw)
    if isinstance(kind, Boolean):
        return raw.strip().lower() in ("true", "1", "yes", "y")
    if isinstance(kind, Integer):
        return int(float(raw))
    if isinstance(kind, Float):
        return float(raw)
    if isinstance(kind, DateTime):
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return raw


def headers(spec: TableSpec) -> list[str]:
    names = [c.name for c in spec.model.__table__.columns if c.name not in SKIP_COLUMNS]
    if spec.model is Dependency:
        names = ["source_component", "target_component"] + [
            n for n in names if n not in ("source_component_id", "target_component_id")
        ]
    if spec.model is TestExecution:
        names = [n for n in names if n != "test_case_pk"]
    return names


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
def load_all(session: Session, directory: Path | None = None) -> dict[str, int]:
    """Load every CSV into the (empty) database. Raises CsvDataError on bad data."""
    directory = Path(directory or data_dir())
    session.info[SUPPRESS] = True
    counts: dict[str, int] = {}
    component_pk: dict[str, int] = {}
    test_pk: dict[str, int] = {}
    try:
        for spec in TABLES:
            path = directory / spec.file
            if not path.exists():
                if spec.required:
                    logger.warning("csv.missing_file", file=str(path))
                counts[spec.table] = 0
                continue
            columns = {c.name: c for c in spec.model.__table__.columns}
            objects = []
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    line = reader.line_num
                    if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
                        continue  # blank line
                    values: dict[str, Any] = {}
                    for name, raw in row.items():
                        if name is None:
                            continue
                        name = name.strip()
                        if spec.model is Dependency and name in ("source_component", "target_component"):
                            key = (raw or "").strip()
                            if key not in component_pk:
                                raise CsvDataError(
                                    f"{spec.file} line {line}: unknown component '{key}' in {name}"
                                )
                            values[f"{name}_id"] = component_pk[key]
                            continue
                        column = columns.get(name)
                        if column is None or name in SKIP_COLUMNS:
                            continue
                        if name in spec.file_columns:
                            if raw and (directory / raw).exists():
                                values[name] = json.loads((directory / raw).read_text(encoding="utf-8"))
                            continue
                        try:
                            decoded = _decode(column, raw)
                        except (ValueError, TypeError) as exc:
                            raise CsvDataError(
                                f"{spec.file} line {line}, column '{name}': {exc}"
                            ) from exc
                        if decoded is not _MISSING:
                            values[name] = decoded
                    if spec.model is TestExecution:
                        test_id = values.get("test_case_id")
                        if test_id not in test_pk:
                            raise CsvDataError(f"{spec.file} line {line}: unknown test case '{test_id}'")
                        values["test_case_pk"] = test_pk[test_id]
                    objects.append(spec.model(**values))
            session.add_all(objects)
            try:
                session.flush()
            except IntegrityError as exc:
                raise CsvDataError(f"{spec.file}: {exc.orig}") from exc
            if spec.model is Component:
                component_pk = {obj.component_id: obj.id for obj in objects}
            if spec.model is TestCase:
                test_pk = {obj.test_case_id: obj.id for obj in objects}
            counts[spec.table] = len(objects)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.info.pop(SUPPRESS, None)
        session.info.pop(DIRTY, None)
    logger.info("csv.loaded", directory=str(directory), **counts)
    return counts


# ---------------------------------------------------------------------------
# write back
# ---------------------------------------------------------------------------
def export_table(spec: TableSpec, engine: Engine, directory: Path | None = None) -> int:
    """Write one table to its CSV file (atomically)."""
    directory = Path(directory or data_dir())
    table = spec.model.__table__
    columns = {c.name: c for c in table.columns}
    with engine.connect() as conn:
        rows = conn.execute(select(table).order_by(table.c.id)).mappings().all()
        component_ids: dict[int, str] = {}
        if spec.model is Dependency:
            component_table = Component.__table__
            component_ids = dict(
                conn.execute(select(component_table.c.id, component_table.c.component_id)).all()
            )
    names = headers(spec)
    out: list[dict[str, str]] = []
    for row in rows:
        record: dict[str, str] = {}
        for name in names:
            if spec.model is Dependency and name in ("source_component", "target_component"):
                record[name] = component_ids.get(row[f"{name}_id"], "")
            elif name in spec.file_columns:
                relative = spec.file_columns[name].format(**dict(row))
                target = directory / relative
                if row[name] is not None and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(row[name], ensure_ascii=False, default=str), encoding="utf-8")
                record[name] = relative if row[name] is not None else ""
            else:
                record[name] = _encode(columns[name], row[name])
        out.append(record)
    _atomic_write(directory / spec.file, names, out)
    return len(out)


def export_all(engine: Engine, directory: Path | None = None) -> dict[str, int]:
    return {spec.table: export_table(spec, engine, directory) for spec in TABLES}


def _atomic_write(path: Path, names: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=names)
            writer.writeheader()
            writer.writerows(rows)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # e.g. the file is open in Excel
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class CsvWriter:
    """Coalesces commits and writes changed tables back from a background thread."""

    def __init__(self, delay_seconds: float = 0.4) -> None:
        self.delay = delay_seconds
        self.engine: Engine | None = None
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def schedule(self, tables: set[str]) -> None:
        with self._lock:
            self._pending |= tables
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="csv-writer", daemon=True)
                self._thread.start()
        self._wake.set()

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            time.sleep(self.delay)
            self._wake.clear()
            self.flush()

    def flush(self) -> None:
        """Write every pending table now (called on shutdown and by tests)."""
        with self._lock:
            tables, self._pending = self._pending, set()
        if not tables or self.engine is None:
            return
        with self._flush_lock:
            for spec in TABLES:
                if spec.table not in tables:
                    continue
                try:
                    export_table(spec, self.engine)
                except Exception as exc:
                    logger.warning("csv.write_failed", file=spec.file, error=str(exc))
                    with self._lock:
                        self._pending.add(spec.table)


writer = CsvWriter()


_write_back_installed = False


def install_write_back(session_factory, engine: Engine) -> None:
    """Track which tables each commit changes and hand them to the writer."""
    global _write_back_installed
    writer.engine = engine
    if _write_back_installed:
        return
    _write_back_installed = True

    @event.listens_for(session_factory, "after_flush")
    def _track(session: Session, _context) -> None:
        if session.info.get(SUPPRESS):
            return
        changed = session.info.setdefault(DIRTY, set())
        for obj in (*session.new, *session.deleted):
            if getattr(obj, "__tablename__", None) in TABLE_BY_NAME:
                changed.add(obj.__tablename__)
        for obj in session.dirty:
            if getattr(obj, "__tablename__", None) in TABLE_BY_NAME and session.is_modified(obj):
                changed.add(obj.__tablename__)

    @event.listens_for(session_factory, "after_commit")
    def _commit(session: Session) -> None:
        tables = session.info.pop(DIRTY, set())
        if tables and not session.info.get(SUPPRESS):
            writer.schedule(tables)

    @event.listens_for(session_factory, "after_rollback")
    def _rollback(session: Session) -> None:
        session.info.pop(DIRTY, None)


# ---------------------------------------------------------------------------
# inspection
# ---------------------------------------------------------------------------
def current_counts(db: Session) -> dict[str, int]:
    return {
        "components": db.query(Component).count(),
        "dependencies": db.query(Dependency).count(),
        "requirements": db.query(Requirement).count(),
        "defects": db.query(Defect).count(),
        "test_cases": db.query(TestCase).count(),
        "test_executions": db.query(TestExecution).count(),
        "ecrs": db.query(ECR).count(),
        "comments": db.query(Comment).count(),
        "evidence": db.query(Evidence).count(),
    }


def files_status(directory: Path | None = None) -> dict[str, Any]:
    directory = Path(directory or data_dir())
    return {
        "data_dir": str(directory),
        "files": {spec.file: (directory / spec.file).exists() for spec in TABLES},
    }
