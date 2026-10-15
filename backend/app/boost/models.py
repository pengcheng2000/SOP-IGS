"""Tables owned by the boost-integrated-unit product; cabinet tables are not touched."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import TimestampMixin, uuid4


class BoostProject(Base, TimestampMixin):
    __tablename__ = "boost_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    document_number: Mapped[str] = mapped_column(String(100), default="")
    document_version: Mapped[str] = mapped_column(String(30), default="A0")
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class BoostSourceFile(Base, TimestampMixin):
    """An uploaded 测试项分类表; rows are immutable and the newest one is current."""

    __tablename__ = "boost_source_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("boost_projects.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    parser_version: Mapped[str] = mapped_column(String(30))
    document: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class BoostGenerationTask(Base, TimestampMixin):
    __tablename__ = "boost_generation_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("boost_projects.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(50), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(String(500), default="等待 Word Worker")
    events: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class BoostGeneratedDocument(Base, TimestampMixin):
    __tablename__ = "boost_generated_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("boost_projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("boost_generation_tasks.id"), unique=True)
    file_path: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict] = mapped_column(JSON)
    validation_report: Mapped[dict] = mapped_column(JSON)


BOOST_TABLES = [model.__table__ for model in (BoostProject, BoostSourceFile, BoostGenerationTask, BoostGeneratedDocument)]
