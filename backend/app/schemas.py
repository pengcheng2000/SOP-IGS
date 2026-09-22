from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from .time_utils import utc_iso


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: str
    display_name: str
    role: str
    csrf_token: str | None = None


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10, max_length=256)
    role: str = Field(default="user", pattern=r"^(admin|user)$")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ProjectUpdate(BaseModel):
    revision: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    document_number: str | None = Field(default=None, max_length=100)
    document_title: str | None = Field(default=None, max_length=200)
    document_version: str | None = Field(default=None, max_length=30)
    product_phase: str | None = Field(default=None, max_length=100)
    test_period: str | None = Field(default=None, max_length=100)
    test_location: str | None = Field(default=None, max_length=200)
    testers: str | None = Field(default=None, max_length=300)
    product_model: str | None = Field(default=None, max_length=200)
    product_serial_no: str | None = Field(default=None, max_length=200)
    product_info: str | None = Field(default=None, max_length=5000)
    project_differences: str | None = Field(default=None, max_length=5000)


class SelectionUpdate(BaseModel):
    revision: int
    test_item_ids: list[str]
    source: str = "manual"


class PhotoUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=200)
    photo_group_id: str | None = None


class PhotoOrderUpdate(BaseModel):
    photo_ids: list[str]


class PhotoGroupCreate(BaseModel):
    test_item_id: str
    title: str = Field(min_length=1, max_length=100)


class PhotoGroupUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class PhotoGroupOrderUpdate(BaseModel):
    photo_group_ids: list[str]


class Recommendation(BaseModel):
    test_item_id: str
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)


class AdviceWarning(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    related_test_item_ids: list[str] = Field(default_factory=list)


class PhotoSuggestion(BaseModel):
    test_item_id: str
    message: str = Field(min_length=1, max_length=500)


class AIAdvicePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_test_items: list[Recommendation] = Field(default_factory=list)
    warnings: list[AdviceWarning] = Field(default_factory=list)
    photo_suggestions: list[PhotoSuggestion] = Field(default_factory=list)

    @field_validator("recommended_test_items")
    @classmethod
    def unique_recommendations(cls, value: list[Recommendation]) -> list[Recommendation]:
        ids = [item.test_item_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("recommended test item ids must be unique")
        return value


class GenerationRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    allow_warnings: bool = False


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    phase: str
    progress_percent: int = 0
    progress_message: str = ""
    heartbeat_at: datetime | None = None
    phase_started_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    diagnostics: dict = Field(default_factory=dict)
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "heartbeat_at",
        "phase_started_at",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
        when_used="json",
    )
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return utc_iso(value)
