"""Project rules for 升压一体机: fields, preflight, snapshot and API payloads."""
from __future__ import annotations

import copy
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Template
from ..time_utils import utc_iso
from .input.model import ERROR, WARNING
from .models import BoostProject, BoostSourceFile
from .settings import BoostSettings, load_manifest

MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def manifest(settings: BoostSettings) -> dict:
    return load_manifest(settings.template_dir)


def current_template(db: Session, settings: BoostSettings) -> Template | None:
    if not (settings.template_dir / "manifest.yaml").is_file():
        return None
    data = manifest(settings)
    return db.scalar(select(Template).where(Template.key == data["template_key"], Template.version == data["version"]))


def latest_source_file(db: Session, project_id: str) -> BoostSourceFile | None:
    return db.scalar(
        select(BoostSourceFile)
        .where(BoostSourceFile.project_id == project_id)
        .order_by(BoostSourceFile.created_at.desc(), BoostSourceFile.id.desc())
        .limit(1)
    )


def issue_counts(issues: list[dict]) -> dict:
    return {
        "error_count": sum(issue.get("severity") == ERROR for issue in issues),
        "warning_count": sum(issue.get("severity") == WARNING for issue in issues),
    }


def source_file_summary(row: BoostSourceFile | None) -> dict | None:
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


def client_document(row: BoostSourceFile) -> dict | None:
    """The stored model with server paths replaced by preview URLs."""
    if row.document is None:
        return None
    document = copy.deepcopy(row.document)

    def convert(image: dict) -> None:
        image.pop("path", None)
        image["url"] = f"/api/boost/source-files/{row.id}/images/{image['id']}"

    for chapter in document.get("chapters", []):
        for item in chapter.get("items", []):
            if item["type"] == "image":
                convert(item["ref"])
            elif item["type"] == "table":
                for cells in item["rows"]:
                    for cell in cells:
                        for image in cell.get("images", []):
                            convert(image)
    return document


def source_file_payload(row: BoostSourceFile) -> dict:
    return {**source_file_summary(row), "issues": row.issues or [], "document": client_document(row)}


def project_payload(db: Session, project: BoostProject) -> dict:
    return {
        "id": project.id,
        "product_type": "boost-integrated-unit",
        "name": project.name,
        "description": project.description,
        "document_number": project.document_number,
        "document_version": project.document_version,
        "fields": project.fields or {},
        "status": project.status,
        "revision": project.revision,
        "source_file": source_file_summary(latest_source_file(db, project.id)),
        "created_at": utc_iso(project.created_at),
        "updated_at": utc_iso(project.updated_at),
    }


def resolve_fields(project: BoostProject, data: dict) -> dict[str, str]:
    stored = project.fields or {}
    values: dict[str, str] = {}
    for field in data.get("fields", []):
        column = field.get("column")
        value = getattr(project, column) if column else stored.get(field["key"], "")
        values[field["key"]] = (value or "").strip()
    if not values.get("project_name"):
        values["project_name"] = project.name
    return values


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


def preflight(db: Session, project: BoostProject, settings: BoostSettings) -> dict:
    data = manifest(settings)
    blockers: list[dict] = []
    warnings: list[dict] = []
    fields = resolve_fields(project, data)
    missing = [field["label"] for field in data.get("fields", []) if field.get("required") and not fields.get(field["key"])]
    if missing:
        blockers.append({"code": "MISSING_REQUIRED_FIELD", "message": "请填写：" + "、".join(missing)})
    source = latest_source_file(db, project.id)
    stats: dict = {}
    if source is None:
        blockers.append({"code": "MISSING_SOURCE_FILE", "message": "请先上传测试项分类表"})
    else:
        counts = issue_counts(source.issues or [])
        stats = {key: value for key, value in (source.summary or {}).items() if key.endswith("_count")}
        if source.status != "parsed" or counts["error_count"]:
            blockers.append({"code": "SOURCE_FILE_INVALID",
                             "message": f"测试项分类表有 {counts['error_count']} 个错误，请修正后重新上传"})
        if counts["warning_count"]:
            warnings.append({"code": "SOURCE_FILE_WARNINGS",
                             "message": f"测试项分类表有 {counts['warning_count']} 条提醒，请确认后继续"})
    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "stats": stats,
        "warning_confirmation_required": bool(warnings),
    }


def snapshot(project: BoostProject, template: Template, source: BoostSourceFile, data: dict) -> dict:
    return {
        "template_key": template.key,
        "template_version": template.version,
        "master_sha256": template.master_sha256,
        "project": {
            "id": project.id,
            "name": project.name,
            "document_number": project.document_number,
            "document_version": project.document_version,
            "fields": dict(project.fields or {}),
            "revision": project.revision,
        },
        "fields": resolve_fields(project, data),
        "source_file": {
            "id": source.id,
            "sha256": source.sha256,
            "original_filename": source.original_filename,
            "parser_version": source.parser_version,
        },
        "document": source.document,
    }
