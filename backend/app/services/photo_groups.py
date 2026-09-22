from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.photo_groups import DEFINITIONS_BY_TEST_ITEM
from ..models import Photo, PhotoGroup, ProjectTestItem

SAMPLE_GROUPS = (
    ("sample_front_closed", "正面关门整体", 1),
    ("sample_front_open", "正面开门整体", 1),
    ("sample_diagonal", "对角 45°", 2),
)


def ensure_project_photo_groups(
    db: Session,
    project_id: str,
    selected_test_item_ids: list[str] | None = None,
) -> list[PhotoGroup]:
    if selected_test_item_ids is None:
        selected_test_item_ids = list(
            db.scalars(
                select(ProjectTestItem.test_item_id).where(
                    ProjectTestItem.project_id == project_id,
                    ProjectTestItem.selected.is_(True),
                )
            )
        )
    existing = db.scalars(select(PhotoGroup).where(PhotoGroup.project_id == project_id)).all()
    existing_keys = {(group.test_item_id, group.key) for group in existing}
    for index, (key, title, minimum) in enumerate(SAMPLE_GROUPS):
        if (None, key) not in existing_keys:
            group = PhotoGroup(project_id=project_id, test_item_id=None, scope="sample",
                               key=key, title=title, sort_order=(index + 1) * 10,
                               source="template", requiredness="recommended", min_photos=minimum,
                               layout_profile="fixed_columns", preferred_columns=2,
                               hint=f"建议至少 {minimum} 张；缺图确认后仍可生成。")
            db.add(group)
            existing.append(group)
    for test_item_id in selected_test_item_ids:
        for definition in DEFINITIONS_BY_TEST_ITEM.get(test_item_id, ()):
            if (test_item_id, definition.key) in existing_keys:
                continue
            group = PhotoGroup(
                project_id=project_id,
                test_item_id=test_item_id,
                template_group_id=definition.id,
                key=definition.key,
                title=definition.title,
                sort_order=definition.sort_order,
                source="template",
                requiredness=definition.requiredness,
                min_photos=definition.min_photos,
                layout_profile=definition.layout_profile,
                preferred_columns=definition.preferred_columns,
                hint=definition.hint,
            )
            db.add(group)
            existing.append(group)
            existing_keys.add((test_item_id, definition.key))
    db.flush()
    return sorted(
        (group for group in existing if group.scope == "sample" or group.test_item_id in set(selected_test_item_ids)),
        key=lambda group: (group.test_item_id or "", group.source == "custom", group.sort_order),
    )


def group_photo_counts(db: Session, project_id: str) -> dict[str, int]:
    return dict(
        db.execute(
            select(Photo.photo_group_id, func.count(Photo.id))
            .join(PhotoGroup, Photo.photo_group_id == PhotoGroup.id)
            .where(PhotoGroup.project_id == project_id, Photo.status == "processed")
            .group_by(Photo.photo_group_id)
        ).all()
    )
