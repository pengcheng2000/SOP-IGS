from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select

from ..db import Base, SessionLocal, engine
from ..models import Template
from .models import CABINET_PLAN_TABLES
from .settings import get_cabinet_plan_settings, load_manifest
from .templates import apply_template_manifest

LOGGER = logging.getLogger(__name__)


def bootstrap_cabinet_plan() -> None:
    """Create cabinet plan tables and folders and register the cabinet plan master; runs after the shared bootstrap."""
    settings = get_cabinet_plan_settings()
    for directory in (
        settings.data_dir,
        settings.sources_dir,
        settings.outputs_dir,
        settings.temp_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine, tables=CABINET_PLAN_TABLES)
    if not (settings.template_dir / "manifest.yaml").is_file() or not settings.master.is_file():
        LOGGER.warning(
            "CabinetPlan template not found at %s; 工商业柜测试方案 is disabled",
            settings.template_dir,
        )
        return
    try:
        manifest = load_manifest(settings.template_dir)
    except (OSError, ValueError):
        LOGGER.exception("工商业柜方案模板配置损坏，仅停用此功能")
        return
    if hashlib.sha256(settings.master.read_bytes()).hexdigest() != manifest["master_sha256"]:
        # A broken cabinet plan template must not stop the cabinet product from starting.
        LOGGER.error(
            "TEMPLATE_HASH_MISMATCH: %s does not match manifest; 工商业柜测试方案 is disabled",
            settings.master,
        )
        return
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
        apply_template_manifest(template, manifest)
