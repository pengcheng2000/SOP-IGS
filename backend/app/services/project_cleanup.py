"""Shared helpers for permanently deleting a project and its stored files."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage import LocalBlobStore

FINISHED_TASK_STATUSES = ("succeeded", "failed")


def ensure_no_active_generation(db: Session, task_model, project_id: str) -> None:
    """Refuse deletion while the Word worker may still read this project's data."""
    active = db.scalar(
        select(task_model.id)
        .where(task_model.project_id == project_id, task_model.status.not_in(FINISHED_TASK_STATUSES))
        .limit(1)
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "项目正在生成文档，请等待完成后再删除")


def remove_project_dirs(project_id: str, roots: list[Path]) -> None:
    """Remove ``<root>/<project_id>`` for each storage root; missing folders are ignored."""
    for root in roots:
        target = LocalBlobStore(root).resolve(project_id)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
