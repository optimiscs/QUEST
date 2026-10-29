from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    run_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    counts: Mapped[dict[str, int]] = mapped_column(JSONB)
    revision: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    listed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Trace(Base):
    __tablename__ = "traces"
    __table_args__ = (UniqueConstraint("run_id", "position"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[str] = mapped_column(String(64))


class TracePayload(Base):
    """Separate large bodies so list queries cannot load them accidentally."""

    __tablename__ = "trace_payloads"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "trace_id"], ["traces.run_id", "traces.id"], ondelete="CASCADE"),
    )
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSON)


class Source(Base):
    __tablename__ = "ingestion_sources"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    size: Mapped[int] = mapped_column(BigInteger)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    body: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)
    revision: Mapped[str] = mapped_column(String(64))
