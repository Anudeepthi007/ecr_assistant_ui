"""CSV files are the system of record: load, validate and write back."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.data import csv_store
from app.database import Base
from app.models import ECR


def _ids(file_name: str, column: str) -> list[str]:
    with open(Path(settings.data_dir) / file_name, newline="", encoding="utf-8") as handle:
        return [row[column] for row in csv.DictReader(handle)]


def test_every_table_has_a_csv_file(database):
    assert all(csv_store.files_status()["files"].values())


def test_the_csv_files_hold_old_and_new_sample_data(database):
    ecrs = _ids("ecrs.csv", "ecr_id")
    assert "ECR-2026-001" in ecrs and "ECR-2026-043" in ecrs
    assert len(_ids("requirements.csv", "requirement_id")) == 64


def test_a_change_is_written_back_to_its_csv_file(db_session):
    db_session.add(ECR(ecr_id="ECR-2099-001", title="Write-back check", description="Created by a test."))
    db_session.commit()
    try:
        csv_store.writer.flush()
        assert "ECR-2099-001" in _ids("ecrs.csv", "ecr_id")
    finally:
        db_session.delete(db_session.query(ECR).filter_by(ecr_id="ECR-2099-001").one())
        db_session.commit()
        csv_store.writer.flush()
    assert "ECR-2099-001" not in _ids("ecrs.csv", "ecr_id")


def test_a_bad_value_names_the_file_line_and_column(tmp_path):
    (tmp_path / "components.csv").write_text(
        "component_id,name,type,criticality_score\nCMP-900,Broken,SERVICE,not-a-number\n",
        encoding="utf-8",
    )
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with pytest.raises(csv_store.CsvDataError, match=r"components\.csv line 2, column 'criticality_score'"):
        csv_store.load_all(sessionmaker(bind=engine)(), tmp_path)
