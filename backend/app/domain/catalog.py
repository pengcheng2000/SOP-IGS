from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

NodeType = Literal["GROUP", "LEAF"]


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: str
    title: str
    parent_id: str | None
    node_type: NodeType
    order: int
    source_level: int


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem("visual_inspection", "外观检查", None, "LEAF", 10, 1),
    CatalogItem("wiring_correctness", "接线正确性检查", None, "LEAF", 20, 1),
    CatalogItem("cabinet_strength", "机柜强度测试", None, "GROUP", 30, 1),
    CatalogItem("cabinet_strength_static", "满载静置", "cabinet_strength", "LEAF", 31, 2),
    CatalogItem("cabinet_strength_lifting", "起吊、称重", "cabinet_strength", "LEAF", 32, 2),
    CatalogItem("cabinet_strength_forklift", "叉举", "cabinet_strength", "LEAF", 33, 2),
    CatalogItem("ingress_protection", "防护等级测试", None, "LEAF", 40, 1),
    CatalogItem("grounding_continuity", "接地连续性试验", None, "LEAF", 50, 1),
    CatalogItem("insulation_withstand", "绝缘耐压测试", None, "LEAF", 60, 1),
    CatalogItem("system_power", "系统供电测试", None, "LEAF", 70, 1),
    CatalogItem("communications", "通讯测试", None, "GROUP", 80, 1),
    CatalogItem("module_data", "模块数据测试", "communications", "LEAF", 81, 2),
    CatalogItem("alarm_protection", "报警和保护测试", "communications", "GROUP", 82, 2),
    CatalogItem("alarm_bms", "BMS", "alarm_protection", "LEAF", 821, 3),
    CatalogItem("alarm_pcs", "PCS", "alarm_protection", "LEAF", 822, 3),
    CatalogItem("alarm_fire", "消防系统", "alarm_protection", "LEAF", 823, 3),
    CatalogItem("alarm_thermal", "热管理系统", "alarm_protection", "LEAF", 824, 3),
    CatalogItem("alarm_start_stop", "启停机功能", "alarm_protection", "LEAF", 825, 3),
    CatalogItem("alarm_emergency_stop", "急停功能", "alarm_protection", "LEAF", 826, 3),
    CatalogItem("signal_test", "信号测试", None, "GROUP", 90, 1),
    CatalogItem("signal_di", "DI采集点信息", "signal_test", "LEAF", 91, 2),
    CatalogItem("signal_do", "DO采集点信息", "signal_test", "LEAF", 92, 2),
    CatalogItem("system_function", "系统功能", None, "GROUP", 100, 1),
    CatalogItem("active_power_control", "有功功率控制功能", "system_function", "LEAF", 101, 2),
    CatalogItem("noise_test", "噪声测试", "system_function", "LEAF", 102, 2),
    CatalogItem("on_off_grid", "并离网测试", "system_function", "LEAF", 103, 2),
    CatalogItem("capacity_test", "容量测试", None, "LEAF", 110, 1),
    CatalogItem("temperature_rise", "温升测试", None, "LEAF", 120, 1),
    CatalogItem("transport_test", "运输测试", None, "LEAF", 130, 1),
)

BY_ID = {item.id: item for item in CATALOG}
BY_TITLE = {item.title: item for item in CATALOG}
LEAF_IDS = frozenset(item.id for item in CATALOG if item.node_type == "LEAF")


def children(parent_id: str | None) -> list[CatalogItem]:
    return sorted((item for item in CATALOG if item.parent_id == parent_id), key=lambda x: x.order)


def descendants(item_id: str) -> list[CatalogItem]:
    result: list[CatalogItem] = []
    stack = list(reversed(children(item_id)))
    while stack:
        item = stack.pop()
        result.append(item)
        stack.extend(reversed(children(item.id)))
    return result


def selected_with_ancestors(selected_leaf_ids: Iterable[str]) -> set[str]:
    selected = set(selected_leaf_ids)
    invalid = selected - LEAF_IDS
    if invalid:
        raise ValueError(f"Invalid leaf ids: {sorted(invalid)}")
    kept = set(selected)
    for item_id in tuple(selected):
        parent_id = BY_ID[item_id].parent_id
        while parent_id:
            kept.add(parent_id)
            parent_id = BY_ID[parent_id].parent_id
    return kept


def display_numbers(selected_leaf_ids: Iterable[str]) -> dict[str, str]:
    kept = selected_with_ancestors(selected_leaf_ids)
    result: dict[str, str] = {}

    def walk(parent_id: str | None, prefix: str) -> None:
        index = 0
        for item in children(parent_id):
            if item.id not in kept:
                continue
            index += 1
            number = f"{prefix}.{index}"
            result[item.id] = number
            walk(item.id, number)

    walk(None, "5")
    return result


def tree_payload(selected_leaf_ids: Iterable[str] = ()) -> list[dict]:
    selected = set(selected_leaf_ids)
    kept = selected_with_ancestors(selected) if selected else set()
    numbers = display_numbers(selected) if selected else {}

    def build(parent_id: str | None) -> list[dict]:
        payload = []
        for item in children(parent_id):
            leaves = [x.id for x in descendants(item.id) if x.node_type == "LEAF"]
            if item.node_type == "LEAF":
                state = "checked" if item.id in selected else "unchecked"
            else:
                count = sum(x in selected for x in leaves)
                state = "unchecked" if count == 0 else ("checked" if count == len(leaves) else "indeterminate")
            payload.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "node_type": item.node_type,
                    "state": state,
                    "display_number": numbers.get(item.id),
                    "included": item.id in kept,
                    "children": build(item.id),
                }
            )
        return payload

    return build(None)

