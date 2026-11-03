"""Project rules for 工商业柜测试方案: fields, preflight, snapshot and API payloads."""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..document_common.model import ERROR, WARNING
from ..models import Template
from ..time_utils import utc_iso
from .models import CabinetPlanProject, CabinetPlanSourceFile
from .settings import CabinetPlanSettings, get_cabinet_plan_settings, load_manifest
from .templates import apply_template_manifest

MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def manifest(settings: CabinetPlanSettings) -> dict:
    return load_manifest(settings.template_dir)


def current_template(db: Session, settings: CabinetPlanSettings) -> Template | None:
    if not (settings.template_dir / "manifest.yaml").is_file():
        return None
    try:
        data = manifest(settings)
    except (OSError, ValueError):
        return None
    if (
        not settings.master.is_file()
        or hashlib.sha256(settings.master.read_bytes()).hexdigest() != data["master_sha256"]
    ):
        return None
    template = db.scalar(
        select(Template).where(
            Template.key == data["template_key"], Template.version == data["version"]
        )
    )
    if template is not None:
        # A rebuilt master can be valid on disk while a running API still has
        # the old registry hash. Resolve it before approval checks/snapshots.
        # Read-only requests do not commit; a mutation persists the metadata
        # together with its own transaction, without committing other work here.
        apply_template_manifest(template, data)
    return template


def latest_source_file(db: Session, project_id: str) -> CabinetPlanSourceFile | None:
    return db.scalar(
        select(CabinetPlanSourceFile)
        .where(CabinetPlanSourceFile.project_id == project_id)
        .order_by(CabinetPlanSourceFile.created_at.desc(), CabinetPlanSourceFile.id.desc())
        .limit(1)
    )


def issue_counts(issues: list[dict]) -> dict:
    return {
        "error_count": sum(issue.get("severity") == ERROR for issue in issues),
        "warning_count": sum(issue.get("severity") == WARNING for issue in issues),
    }


def source_file_summary(row: CabinetPlanSourceFile | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "original_filename": row.original_filename,
        "size_bytes": row.size_bytes,
        "parser_version": row.parser_version,
        "created_at": utc_iso(row.created_at),
        **(row.summary or {}),
        **issue_counts(row.issues or []),
    }


def client_document(row: CabinetPlanSourceFile) -> dict | None:
    """The stored model with server paths replaced by preview URLs."""
    if row.document is None:
        return None
    document = copy.deepcopy(row.document)

    def convert(image: dict) -> None:
        image.pop("path", None)
        image["url"] = f"/api/cabinet-plans/source-files/{row.id}/images/{image['id']}"

    def walk(value):
        if isinstance(value, dict):
            if {"id", "path", "px_w", "px_h", "sha256"} <= value.keys():
                convert(value)
            else:
                for child in value.values():
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
    return document


def source_file_payload(row: CabinetPlanSourceFile) -> dict:
    return {
        **source_file_summary(row),
        "issues": row.issues or [],
        "document": client_document(row),
    }


def project_payload(db: Session, project: CabinetPlanProject) -> dict:
    source = latest_source_file(db, project.id)
    try:
        data = manifest(get_cabinet_plan_settings())
    except (OSError, ValueError):
        from .input import FIELDS

        data = {"fields": [{"key": key} for key in FIELDS]}
    values, origins = resolved_metadata(project, data, source)
    return {
        "id": project.id,
        "product_type": "cabinet-test-plan",
        "business_type": "cabinet",
        "document_kind": "plan",
        "resolved_fields": values,
        "field_sources": origins,
        "name": project.name,
        "description": project.description,
        "document_number": values.get("document_code", ""),
        "document_version": values.get("document_version", ""),
        "fields": project.fields or {},
        "status": project.status,
        "revision": project.revision,
        "source_file": source_file_summary(source),
        "created_at": utc_iso(project.created_at),
        "updated_at": utc_iso(project.updated_at),
    }


def resolved_metadata(
    project: CabinetPlanProject, data: dict, source: CabinetPlanSourceFile | None
):
    extracted = (source.document or {}).get("extra", {}).get("fields", {}) if source else {}
    values, origins = {}, {}
    for field in data.get("fields", []):
        key = field["key"]
        entry = extracted.get(key, {})
        value = (entry.get("value") or "").strip()
        supplement = (project.fields or {}).get(key, "").strip()
        values[key] = value or supplement
        origins[key] = {
            "kind": "excel" if value else "supplement" if supplement else "missing",
            "cell": entry.get("source", ""),
            "source_file_id": source.id if source else None,
        }
    return values, origins


def resolve_fields(
    project: CabinetPlanProject, data: dict, source: CabinetPlanSourceFile | None = None
) -> dict[str, str]:
    return resolved_metadata(project, data, source)[0]


def validate_fields(data: dict, values: dict[str, str]) -> list[str]:
    allowed = {field["key"]: field for field in data.get("fields", []) if not field.get("column")}
    problems = [f"未知字段：{key}" for key in values if key not in allowed]
    for key, value in values.items():
        field = allowed.get(key)
        if field is None:
            continue
        if field.get("type") == "month" and value and not MONTH_PATTERN.fullmatch(value):
            problems.append(f"{field['label']}格式应为 YYYY-MM")
            continue
        limit = 2000 if field.get("multiline") else 200
        if len(value) > limit:
            problems.append(f"{field['label']}超过 {limit} 个字符")
    return problems


def preflight(db: Session, project: CabinetPlanProject, settings: CabinetPlanSettings) -> dict:
    if current_template(db, settings) is None:
        return {
            "ready": False,
            "blockers": [
                {"code": "TEMPLATE_UNAVAILABLE", "message": "工商业柜方案模板不可用，请联系管理员"}
            ],
            "warnings": [],
            "stats": {},
            "warning_confirmation_required": False,
        }
    data = manifest(settings)
    blockers: list[dict] = []
    warnings: list[dict] = []
    source = latest_source_file(db, project.id)
    fields = resolve_fields(project, data, source)
    missing = [
        field["label"]
        for field in data.get("fields", [])
        if field.get("required") and not fields.get(field["key"])
    ]
    invalid = validate_fields(data, fields)
    if invalid:
        blockers.append({"code": "INVALID_FIELD", "message": "；".join(invalid)})
    if missing:
        blockers.append(
            {"code": "MISSING_REQUIRED_FIELD", "message": "请填写：" + "、".join(missing)}
        )
    source = latest_source_file(db, project.id)
    stats: dict = {}
    if source is None:
        blockers.append({"code": "MISSING_SOURCE_FILE", "message": "请先上传测试需求表"})
    else:
        counts = issue_counts(source.issues or [])
        stats = {
            key: value for key, value in (source.summary or {}).items() if key.endswith("_count")
        }
        if source.status != "parsed" or counts["error_count"]:
            blockers.append(
                {
                    "code": "SOURCE_FILE_INVALID",
                    "message": f"测试需求表有 {counts['error_count']} 个错误，请修正后重新上传",
                }
            )
        if counts["warning_count"]:
            warnings.append(
                {
                    "code": "SOURCE_FILE_WARNINGS",
                    "message": f"测试需求表有 {counts['warning_count']} 条提醒，请确认后继续",
                }
            )
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "stats": stats,
        "warning_confirmation_required": bool(warnings),
    }


def snapshot(
    project: CabinetPlanProject, template: Template, source: CabinetPlanSourceFile, data: dict
) -> dict:
    values, origins = resolved_metadata(project, data, source)
    return {
        "generation_date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
        "field_sources": origins,
        "template_key": template.key,
        "template_version": template.version,
        "master_sha256": data["master_sha256"],
        "project": {
            "id": project.id,
            "name": project.name,
            "document_number": project.document_number,
            "document_version": project.document_version,
            "fields": dict(project.fields or {}),
            "revision": project.revision,
        },
        "fields": values,
        "source_file": {
            "id": source.id,
            "sha256": source.sha256,
            "original_filename": source.original_filename,
            "parser_version": source.parser_version,
        },
        "document": source.document,
    }
