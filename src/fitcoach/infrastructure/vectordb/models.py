"""Read-only mapping of the exercises corpus loaded by ``infra/vector-db``.

Mirrors the DDL in ``infra/vector-db/ddl/001_*_part-01.sql``. The application
only ever SELECTs from these tables; there is no migration that owns them and
no Alembic revision should ever touch them.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, BigInteger, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 384 dimensions: sentence-transformers/all-MiniLM-L6-v2, the model the loader
# used. Changing it invalidates every stored vector.
EMBEDDING_DIMENSIONS = 384


class VectorBase(DeclarativeBase):
    """Separate declarative base: these tables live in a different database."""


class ExerciseRecord(VectorBase):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    body_part: Mapped[str | None] = mapped_column(Text)
    equipment: Mapped[str | None] = mapped_column(Text)
    muscle_group: Mapped[str | None] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    secondary_muscles: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    instructions_en: Mapped[str | None] = mapped_column(Text)
    instructions_tr: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_vector: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
