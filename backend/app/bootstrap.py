from __future__ import annotations

import hashlib

import yaml
from sqlalchemy import inspect, select, text

from .config import get_settings
from .db import Base, SessionLocal, engine
from .domain.catalog import CATALOG
from .domain.photo_groups import DEFINITION_BY_ID, PHOTO_GROUP_DEFINITIONS
from .models import (
    AuthIdentity,
    PhotoGroup,
    Template,
    TemplatePhotoGroupDefinition,
    TemplateSection,
    TestItem,
    User,
)
from .sample_migration import upgrade_sample_scope
from .security import hash_password
from .services.template_approval import apply_manifest_approval

COMPAT_COLUMNS = {
    "project_test_items": {
        "result_note": "TEXT NOT NULL DEFAULT ''",
    },
    "photo_groups": {
        "template_group_id": "VARCHAR(160)",
        "source": "VARCHAR(20) NOT NULL DEFAULT 'custom'",
        "requiredness": "VARCHAR(20) NOT NULL DEFAULT 'recommended'",
        "min_photos": "INTEGER NOT NULL DEFAULT 0",
        "layout_profile": "VARCHAR(40) NOT NULL DEFAULT 'adaptive_grid'",
        "preferred_columns": "INTEGER",
        "hint": "VARCHAR(500) NOT NULL DEFAULT ''",
    },
    "document_generation_tasks": {
        "progress_percent": "INTEGER NOT NULL DEFAULT 0",
        "progress_message": "VARCHAR(500) NOT NULL DEFAULT '等待 Word Worker'",
        "phase_started_at": "DATETIME",
        "started_at": "DATETIME",
        "completed_at": "DATETIME",
        "diagnostics": "JSON NOT NULL DEFAULT '{}'",
    },
}


def ensure_compatibility_columns() -> None:
    schema = inspect(engine)
    dialect = engine.dialect.name
    with engine.begin() as connection:
        for table_name, definitions in COMPAT_COLUMNS.items():
            existing = {column["name"] for column in schema.get_columns(table_name)}
            for column_name, sql_type in definitions.items():
                if column_name not in existing:
                    if dialect == "postgresql":
                        sql_type = sql_type.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}")
                    )


def bootstrap() -> None:
    settings = get_settings()
    for directory in (
        settings.data_root,
        settings.originals_dir,
        settings.processed_dir,
        settings.outputs_dir,
        settings.temp_dir,
        settings.data_root / "logs",
        settings.data_root / "backups",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    ensure_compatibility_columns()
    with engine.begin() as connection:
        upgrade_sample_scope(connection)

    manifest_path = settings.template_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    master = settings.template_dir / "master.docx"
    actual_hash = hashlib.sha256(master.read_bytes()).hexdigest()
    if actual_hash != manifest["master_sha256"]:
        raise RuntimeError("TEMPLATE_HASH_MISMATCH: master.docx does not match manifest")

    with SessionLocal.begin() as session:
        template = session.scalar(
            select(Template).where(
                Template.key == manifest["template_key"], Template.version == manifest["version"]
            )
        )
        if template is None:
            template = Template(
                key=manifest["template_key"],
                version=manifest["version"],
                source_sha256=manifest["source_sha256"],
                master_sha256=manifest["master_sha256"],
                manifest_version=manifest["manifest_version"],
                status="review_required",
            )
            session.add(template)
            session.flush()
        else:
            template.source_sha256 = manifest["source_sha256"]
            template.master_sha256 = manifest["master_sha256"]
            template.manifest_version = manifest["manifest_version"]
        apply_manifest_approval(template, manifest, actual_hash)
        for item in CATALOG:
            section = session.get(TemplateSection, item.id)
            if section is None:
                section = TemplateSection(
                    id=item.id,
                    template_id=template.id,
                    title=item.title,
                    source_level=item.source_level,
                    sort_order=item.order,
                    selector={"title": item.title, "num_id": 2, "level": item.source_level},
                    photo_anchor={"strategy": "before-test-conclusion-or-next-heading"},
                )
                session.add(section)
                session.flush()
            if session.get(TestItem, item.id) is None:
                session.add(TestItem(id=item.id, template_section_id=item.id,
                                     parent_id=item.parent_id, title=item.title,
                                     node_type=item.node_type, sort_order=item.order))
                session.flush()

        session.flush()
        for definition in PHOTO_GROUP_DEFINITIONS:
            row = session.get(TemplatePhotoGroupDefinition, definition.id)
            values = {
                "template_id": template.id,
                "test_item_id": definition.test_item_id,
                "key": definition.key,
                "title": definition.title,
                "sort_order": definition.sort_order,
                "requiredness": definition.requiredness,
                "min_photos": definition.min_photos,
                "layout_profile": definition.layout_profile,
                "preferred_columns": definition.preferred_columns,
                "hint": definition.hint,
            }
            if row is None:
                session.add(TemplatePhotoGroupDefinition(id=definition.id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

        session.flush()
        for group in session.scalars(select(PhotoGroup)).all():
            if group.template_group_id:
                definition = DEFINITION_BY_ID.get(group.template_group_id)
            else:
                direct_id = f"{group.test_item_id}:{group.key}"
                definition = DEFINITION_BY_ID.get(direct_id)
                if definition is None and group.key == "test_photos":
                    generic_id = f"{group.test_item_id}:test_photos"
                    definition = DEFINITION_BY_ID.get(generic_id)
            if definition is not None:
                group.template_group_id = definition.id
                group.key = definition.key
                group.title = definition.title
                group.sort_order = definition.sort_order
                group.source = "template"
                group.requiredness = definition.requiredness
                group.min_photos = definition.min_photos
                group.layout_profile = definition.layout_profile
                group.preferred_columns = definition.preferred_columns
                group.hint = definition.hint
            elif group.key == "test_photos":
                group.source = "custom"
                group.title = "历史未分类照片"
                group.requiredness = "optional"
                group.layout_profile = "adaptive_grid"
                group.hint = "升级前上传的照片，请拖入合适的模板分组。"

        identity = session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == "local",
                AuthIdentity.provider_user_id == settings.bootstrap_admin_username,
            )
        )
        if identity is None:
            user = User(display_name=settings.bootstrap_admin_username, role="admin")
            session.add(user)
            session.flush()
            session.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="local",
                    provider_user_id=settings.bootstrap_admin_username,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                )
            )


if __name__ == "__main__":
    bootstrap()
    print("SOP-IGS database and storage initialized.")
