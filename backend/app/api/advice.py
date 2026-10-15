from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..domain.catalog import CATALOG
from ..models import AIAdvice, Photo, PhotoGroup, User
from ..services.ai_advisory import AIAdviceError, get_ai_client
from ..time_utils import utc_iso
from .deps import current_user, require_csrf
from .projects import get_project_or_404

router = APIRouter(tags=["ai-advice"])


def _run_advice(advice_id: str, project_payload: dict, items: list[dict], photos: list[dict]) -> None:
    with SessionLocal() as db:
        advice = db.get(AIAdvice, advice_id)
        if advice is None:
            return
        try:
            result = get_ai_client().advise(project_payload, items, photos)
            advice.status = "succeeded"
            advice.response = result.model_dump()
        except AIAdviceError as exc:
            advice.status = "unavailable" if exc.code == "AI_UNAVAILABLE" else "invalid"
            advice.error_code = exc.code
        db.commit()


@router.post("/projects/{project_id}/ai-advice", status_code=202)
def request_advice(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_csrf),
) -> dict:
    project = get_project_or_404(db, project_id, user)
    project_payload = {
        "name": project.name,
        "description": project.description,
        "product_model": project.product_model,
        "product_info": project.product_info,
        "project_differences": project.project_differences,
    }
    photos = [
        {"test_item_id": test_item_id, "caption": caption or ""}
        for test_item_id, caption in db.execute(
            select(PhotoGroup.test_item_id, Photo.caption)
            .join(Photo, Photo.photo_group_id == PhotoGroup.id)
            .where(PhotoGroup.project_id == project_id, Photo.status == "processed")
        )
    ]
    digest = hashlib.sha256(
        json.dumps({"project": project_payload, "photos": photos}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    cached = db.scalar(
        select(AIAdvice).where(
            AIAdvice.project_id == project_id,
            AIAdvice.input_hash == digest,
            AIAdvice.status == "succeeded",
        )
    )
    if cached:
        return {"id": cached.id, "status": cached.status, "response": cached.response, "cached": True}
    advice = AIAdvice(
        project_id=project_id,
        input_hash=digest,
        model=get_settings().llm_model or "",
    )
    db.add(advice)
    db.commit()
    items = [
        {"test_item_id": item.id, "title": item.title}
        for item in CATALOG
        if item.node_type == "LEAF"
    ]
    background_tasks.add_task(_run_advice, advice.id, project_payload, items, photos)
    return {"id": advice.id, "status": advice.status, "cached": False}


@router.get("/projects/{project_id}/ai-advice")
def latest_advice(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    get_project_or_404(db, project_id, user)
    advice = db.scalar(
        select(AIAdvice).where(AIAdvice.project_id == project_id).order_by(AIAdvice.created_at.desc())
    )
    if advice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "尚无 AI 建议")
    return {
        "id": advice.id,
        "status": advice.status,
        "response": advice.response,
        "error_code": advice.error_code,
        "created_at": utc_iso(advice.created_at),
    }
