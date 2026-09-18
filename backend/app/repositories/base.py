"""Generic repository helpers (repository pattern over SQLAlchemy)."""
from __future__ import annotations

from typing import Generic, Iterable, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]
    key_field: str = "id"

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, limit: int | None = None) -> list[ModelT]:
        stmt = select(self.model)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def get(self, key: str) -> ModelT | None:
        column = getattr(self.model, self.key_field)
        return self.db.execute(select(self.model).where(column == key)).scalars().first()

    def get_many(self, keys: Iterable[str]) -> list[ModelT]:
        keys = list(keys)
        if not keys:
            return []
        column = getattr(self.model, self.key_field)
        return list(self.db.execute(select(self.model).where(column.in_(keys))).scalars().all())

    def count(self) -> int:
        from sqlalchemy import func

        return int(self.db.execute(select(func.count()).select_from(self.model)).scalar() or 0)

    def add(self, entity: ModelT) -> ModelT:
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def bulk_add(self, entities: Sequence[ModelT]) -> int:
        self.db.add_all(entities)
        self.db.commit()
        return len(entities)
