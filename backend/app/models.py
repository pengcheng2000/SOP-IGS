from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uuid4() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthIdentity(Base, TimestampMixin):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_user_id: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user: Mapped[User] = relationship()


class LoginSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship()


class Template(Base, TimestampMixin):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(30))
    source_sha256: Mapped[str] = mapped_column(String(64))
    master_sha256: Mapped[str] = mapped_column(String(64))
    manifest_version: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    __table_args__ = (UniqueConstraint("key", "version"),)


class TemplateSection(Base):
    __tablename__ = "template_sections"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(150))
    source_level: Mapped[int] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer)
    selector: Mapped[dict] = mapped_column(JSON, default=dict)
    photo_anchor: Mapped[dict] = mapped_column(JSON, default=dict)


class TestItem(Base):
    __tablename__ = "test_items"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    template_section_id: Mapped[str] = mapped_column(ForeignKey("template_sections.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("test_items.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(150))
    node_type: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer)


class TemplatePhotoGroupDefinition(Base):
    __tablename__ = "template_photo_group_definitions"
    __table_args__ = (UniqueConstraint("template_id", "test_item_id", "key"),)

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    test_item_id: Mapped[str] = mapped_column(ForeignKey("test_items.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer)
    requiredness: Mapped[str] = mapped_column(String(20), default="recommended")
    min_photos: Mapped[int] = mapped_column(Integer, default=0)
    layout_profile: Mapped[str] = mapped_column(String(40), default="adaptive_grid")
    preferred_columns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hint: Mapped[str] = mapped_column(String(500), default="")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    document_number: Mapped[str] = mapped_column(String(100), default="")
    document_title: Mapped[str] = mapped_column(String(200), default="")
    document_version: Mapped[str] = mapped_column(String(30), default="V01")
    product_phase: Mapped[str] = mapped_column(String(100), default="")
    test_period: Mapped[str] = mapped_column(String(100), default="")
    test_location: Mapped[str] = mapped_column(String(200), default="")
    testers: Mapped[str] = mapped_column(String(300), default="")
    product_model: Mapped[str] = mapped_column(String(200), default="")
    product_serial_no: Mapped[str] = mapped_column(String(200), default="")
    product_info: Mapped[str] = mapped_column(Text, default="")
    project_differences: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ProjectTestItem(Base, TimestampMixin):
    __tablename__ = "project_test_items"
    __table_args__ = (UniqueConstraint("project_id", "test_item_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    test_item_id: Mapped[str] = mapped_column(ForeignKey("test_items.id"), index=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_source: Mapped[str] = mapped_column(String(30), default="manual")


class PhotoGroup(Base, TimestampMixin):
    __tablename__ = "photo_groups"
    __table_args__ = (
        UniqueConstraint("project_id", "test_item_id", "key"),
        CheckConstraint("(scope = 'sample' AND test_item_id IS NULL) OR (scope = 'test_item' AND test_item_id IS NOT NULL)", name="ck_photo_group_scope"),
        Index("uq_sample_group_key", "project_id", "key", unique=True,
              sqlite_where=text("scope = 'sample'"), postgresql_where=text("scope = 'sample'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    test_item_id: Mapped[str | None] = mapped_column(ForeignKey("test_items.id"), index=True, nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="test_item", server_default="test_item")
    template_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("template_photo_group_definitions.id"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(50), default="test_photos")
    title: Mapped[str] = mapped_column(String(100), default="测试照片")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="custom")
    requiredness: Mapped[str] = mapped_column(String(20), default="recommended")
    min_photos: Mapped[int] = mapped_column(Integer, default=0)
    layout_profile: Mapped[str] = mapped_column(String(40), default="adaptive_grid")
    preferred_columns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hint: Mapped[str] = mapped_column(String(500), default="")


class Photo(Base, TimestampMixin):
    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    photo_group_id: Mapped[str] = mapped_column(ForeignKey("photo_groups.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str] = mapped_column(Text)
    processed_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    original_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentGenerationTask(Base, TimestampMixin):
    __tablename__ = "document_generation_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
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
    phase_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentTaskEvent(Base):
    __tablename__ = "document_task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("document_generation_tasks.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(String(50))
    progress_percent: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeneratedDocument(Base, TimestampMixin):
    __tablename__ = "generated_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("document_generation_tasks.id"), unique=True)
    file_path: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(30))
    layout_version: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict] = mapped_column(JSON)
    validation_report: Mapped[dict] = mapped_column(JSON)


class AIAdvice(Base, TimestampMixin):
    __tablename__ = "ai_advice"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="openai-compatible")
    model: Mapped[str] = mapped_column(String(100), default="")
    schema_version: Mapped[str] = mapped_column(String(20), default="1")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
