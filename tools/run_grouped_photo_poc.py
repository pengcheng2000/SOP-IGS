from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.services.docx import (
    DocPhotoGroup,
    GenerationInput,
    generate_docx,
    validate_docx,
)
from app.services.docx.com_finalizer import finalize_with_word
from run_docx_poc import make_images


def run(output_dir: Path, use_word: bool) -> list[dict]:
    master = ROOT / "templates" / "liquid-cooled-cabinet" / "v1" / "master.docx"
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = make_images(output_dir / "fixtures", 16)
    cases = {
        "fire-categories": (
            ("alarm_fire",),
            {
                "alarm_fire": (
                    DocPhotoGroup("smoke", "smoke", "烟感", fixtures[0:3], "fire_two_column", 2, sort_order=10),
                    DocPhotoGroup("temperature", "temperature", "温感", fixtures[3:4], "fire_two_column", 2, sort_order=20),
                    DocPhotoGroup("gas-low", "gas_low", "可燃气体低报", fixtures[4:6], "fire_two_column", 2, sort_order=50),
                )
            },
        ),
        "module-categories": (
            ("module_data",),
            {
                "module_data": (
                    DocPhotoGroup("dehumidifier", "dehumidifier", "除湿机", fixtures[0:4], "fixed_columns", 3, sort_order=10),
                    DocPhotoGroup("charging", "charging", "充电", fixtures[4:7], "fixed_columns", 2, sort_order=20),
                    DocPhotoGroup("parallel", "parallel_operation", "多机并联", fixtures[7:8], "fixed_columns", 2, sort_order=30),
                )
            },
        ),
        "temperature-curve": (
            ("temperature_rise",),
            {
                "temperature_rise": (
                    DocPhotoGroup("curve", "temperature_curve", "温升曲线", fixtures[8:9], "temperature_curve", 1),
                )
            },
        ),
        "lifting-required": (
            ("cabinet_strength_lifting",),
            {
                "cabinet_strength_lifting": (
                    DocPhotoGroup("lifting", "lifting_process", "吊装过程", fixtures[9:12], "adaptive_grid", 2, sort_order=10),
                    DocPhotoGroup("weight", "weight_display", "重量显示", fixtures[12:13], "full_width_figure", 1, sort_order=20),
                    DocPhotoGroup("custom", "custom_after", "项目补充证据", fixtures[13:16], "adaptive_grid", None, "custom", 1000),
                )
            },
        ),
    }
    reports = []
    for name, (selected, groups) in cases.items():
        destination = output_dir / f"{name}.docx"
        generation = generate_docx(
            master,
            destination,
            GenerationInput(
                project={"name": f"分组 PoC {name}", "document_title": f"分组 PoC {name}"},
                selected_test_item_ids=selected,
                photo_groups_by_test_item=groups,
            ),
        )
        pre_word = validate_docx(destination)
        word = finalize_with_word(destination) if use_word else None
        post_word = validate_docx(destination)
        reports.append(
            {
                "case": name,
                "file": str(destination),
                "generation": generation,
                "pre_word": pre_word,
                "word": word,
                "post_word": post_word,
            }
        )
    (output_dir / "report.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "grouped-poc")
    parser.add_argument("--word", action="store_true")
    args = parser.parse_args()
    results = run(args.output, args.word)
    print(json.dumps({"cases": len(results), "output": str(args.output)}, ensure_ascii=False))

