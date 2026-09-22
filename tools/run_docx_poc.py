from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.docx import (
    DocPhoto,
    GenerationInput,
    generate_docx,
    validate_docx,
)
from app.services.docx.com_finalizer import finalize_with_word


def make_images(directory: Path, count: int) -> tuple[DocPhoto, ...]:
    directory.mkdir(parents=True, exist_ok=True)
    ratios = ((1600, 900), (900, 1600), (1200, 1200), (2000, 600), (700, 1800))
    result = []
    for index in range(count):
        width, height = ratios[index % len(ratios)]
        image = Image.new("RGB", (width, height), (28 + index * 7 % 160, 112, 103))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, width - 20, height - 20), outline="white", width=max(2, width // 250))
        draw.text((40, 40), f"SOP POC {index + 1}", fill="white")
        path = directory / f"image-{index + 1}.jpg"
        image.save(path, quality=86)
        result.append(DocPhoto(f"p{index + 1}", path, f"验证照片 {index + 1}" if index % 2 else ""))
    return tuple(result)


def run(output_dir: Path, use_word: bool) -> list[dict]:
    master = ROOT / "templates" / "liquid-cooled-cabinet" / "v1" / "master.docx"
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        ("single-deep-leaf", ("alarm_bms",), 0),
        ("partial-groups", ("cabinet_strength_lifting", "alarm_bms", "signal_do"), 0),
        *[(f"photos-{count}", ("visual_inspection",), count) for count in (1, 2, 3, 4, 5, 8, 10)],
    ]
    reports = []
    for name, selected, count in cases:
        photos = make_images(output_dir / "fixtures" / name, count) if count else ()
        destination = output_dir / f"{name}.docx"
        generation = generate_docx(
            master,
            destination,
            GenerationInput(
                project={
                    "name": f"PoC {name}",
                    "document_title": f"PoC {name}",
                    "document_version": "V01",
                    "product_model": "POC-MODEL",
                },
                selected_test_item_ids=selected,
                photos_by_test_item={"visual_inspection": photos} if photos else {},
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
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "poc")
    parser.add_argument("--word", action="store_true", help="Run Microsoft Word COM finalization")
    args = parser.parse_args()
    results = run(args.output, args.word)
    print(json.dumps({"cases": len(results), "output": str(args.output)}, ensure_ascii=False))

