from __future__ import annotations

from dataclasses import dataclass

from .catalog import CATALOG


@dataclass(frozen=True, slots=True)
class PhotoGroupDefinition:
    id: str
    test_item_id: str
    key: str
    title: str
    sort_order: int
    requiredness: str
    min_photos: int
    layout_profile: str = "adaptive_grid"
    preferred_columns: int | None = None
    hint: str = ""


def _definition(
    test_item_id: str,
    key: str,
    title: str,
    sort_order: int,
    requiredness: str = "recommended",
    min_photos: int = 0,
    layout_profile: str = "adaptive_grid",
    preferred_columns: int | None = None,
    hint: str = "",
) -> PhotoGroupDefinition:
    return PhotoGroupDefinition(
        id=f"{test_item_id}:{key}",
        test_item_id=test_item_id,
        key=key,
        title=title,
        sort_order=sort_order,
        requiredness=requiredness,
        min_photos=min_photos,
        layout_profile=layout_profile,
        preferred_columns=preferred_columns,
        hint=hint,
    )


SPECIAL_DEFINITIONS: tuple[PhotoGroupDefinition, ...] = (
    _definition(
        "cabinet_strength_static",
        "open_door",
        "开门照片",
        10,
        "required",
        1,
        hint="母版明确要求至少包含开门照片。",
    ),
    _definition(
        "cabinet_strength_lifting",
        "lifting_process",
        "吊装过程",
        10,
        "required",
        1,
        preferred_columns=2,
        hint="母版明确要求至少包含吊装过程照片。",
    ),
    _definition(
        "cabinet_strength_lifting",
        "weight_display",
        "重量显示",
        20,
        "required",
        1,
        layout_profile="full_width_figure",
        preferred_columns=1,
        hint="母版明确要求至少包含重量照片。",
    ),
    _definition(
        "cabinet_strength_forklift",
        "forklift_process",
        "叉举过程",
        10,
        "required",
        1,
        preferred_columns=2,
        hint="母版明确要求至少包含叉举过程照片。",
    ),
    _definition(
        "cabinet_strength_forklift",
        "after_open_door",
        "测试后开门",
        20,
        "required",
        1,
        hint="母版明确要求至少包含测试后开门照片。",
    ),
    _definition(
        "module_data",
        "dehumidifier",
        "除湿机",
        10,
        layout_profile="fixed_columns",
        preferred_columns=3,
        hint="上传 EMS/BMS 与除湿机等设备通讯数据截图。",
    ),
    _definition(
        "module_data",
        "charging",
        "充电",
        20,
        layout_profile="fixed_columns",
        preferred_columns=2,
        hint="上传 EMS、PCS、BMS 充电通讯数据截图。",
    ),
    _definition(
        "module_data",
        "parallel_operation",
        "多机并联",
        30,
        "optional",
        layout_profile="fixed_columns",
        preferred_columns=2,
        hint="仅产品规格书包含多机并联场景时上传。",
    ),
    _definition(
        "alarm_bms",
        "alarm_evidence",
        "报警图片展示",
        10,
        layout_profile="fixed_columns",
        preferred_columns=2,
        hint="上传必测报警项的触发和系统显示截图。",
    ),
    _definition("alarm_fire", "smoke", "烟感", 10, layout_profile="fire_two_column", preferred_columns=2),
    _definition("alarm_fire", "temperature", "温感", 20, layout_profile="fire_two_column", preferred_columns=2),
    _definition("alarm_fire", "aerosol", "气溶胶喷洒", 30, layout_profile="fire_two_column", preferred_columns=2),
    _definition("alarm_fire", "gas_fault", "可燃气体故障", 40, layout_profile="fire_two_column", preferred_columns=2),
    _definition("alarm_fire", "gas_low", "可燃气体低报", 50, layout_profile="fire_two_column", preferred_columns=2),
    _definition("alarm_fire", "gas_high", "可燃气体高报", 60, layout_profile="fire_two_column", preferred_columns=2),
    _definition(
        "temperature_rise",
        "temperature_curve",
        "温升曲线",
        10,
        layout_profile="temperature_curve",
        preferred_columns=1,
        hint="温升曲线以全宽图片写入温升数据表末行。",
    ),
)


SPECIAL_ITEM_IDS = frozenset(item.test_item_id for item in SPECIAL_DEFINITIONS)
GENERIC_DEFINITIONS = tuple(
    _definition(
        item.id,
        "test_photos",
        "测试照片",
        10,
        hint="未上传照片时会在生成前提醒，但不会阻止生成。",
    )
    for item in CATALOG
    if item.node_type == "LEAF" and item.id not in SPECIAL_ITEM_IDS
)
PHOTO_GROUP_DEFINITIONS = (*SPECIAL_DEFINITIONS, *GENERIC_DEFINITIONS)
DEFINITION_BY_ID = {item.id: item for item in PHOTO_GROUP_DEFINITIONS}
DEFINITIONS_BY_TEST_ITEM: dict[str, tuple[PhotoGroupDefinition, ...]] = {
    test_item_id: tuple(
        sorted(
            (item for item in PHOTO_GROUP_DEFINITIONS if item.test_item_id == test_item_id),
            key=lambda item: item.sort_order,
        )
    )
    for test_item_id in {item.test_item_id for item in PHOTO_GROUP_DEFINITIONS}
}

