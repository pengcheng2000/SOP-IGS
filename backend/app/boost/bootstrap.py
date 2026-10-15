from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select

from ..db import Base, SessionLocal, engine
from ..models import Template
from .models import BOOST_TABLES
from .settings import get_boost_settings, load_manifest

LOGGER = logging.getLogger(__name__)


def bootstrap_boost() -> None:
    """Create boost tables and data folders and register the boost master; runs after the shared bootstrap."""
    settings = get_boost_settings()
    for directory in (settings.data_dir, settings.sources_dir, settings.outputs_dir, settings.temp_dir):
        directory.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine, tables=BOOST_TABLES)
    if not (settings.template_dir / "manifest.yaml").is_file() or not settings.master.is_file():
        LOGGER.warning("Boost template not found at %s; 升压一体机 is disabled", settings.template_dir)
        return
    manifest = load_manifest(settings.template_dir)
    if hashlib.sha256(settings.master.read_bytes()).hexdigest() != manifest["master_sha256"]:
        # A broken boost template must not stop the cabinet product from starting.
        LOGGER.error("TEMPLATE_HASH_MISMATCH: %s does not match manifest; 升压一体机 is disabled", settings.master)
        return
    with SessionLocal.begin() as session:
        template = session.scalar(
            select(Template).where(Template.key == manifest["template_key"], Template.version == manifest["version"])
        )
        if template is None:
            session.add(Template(
                key=manifest["template_key"],
                version=manifest["version"],
                source_sha256=manifest["source_sha256"],
                master_sha256=manifest["master_sha256"],
                manifest_version=manifest["manifest_version"],
                status="review_required",
            ))
        else:
            template.source_sha256 = manifest["source_sha256"]
            template.master_sha256 = manifest["master_sha256"]
            template.manifest_version = manifest["manifest_version"]
