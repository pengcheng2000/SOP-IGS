from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from template_inspector import inspect

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()
    expected = inspect(args.expected)
    actual = inspect(args.actual)
    keys = ("tables", "floating_drawings", "sections")
    differences = {key: [expected[key], actual[key]] for key in keys if expected[key] != actual[key]}
    print(json.dumps({"differences": differences, "actual": actual}, ensure_ascii=False, indent=2))
    sys.exit(1 if differences else 0)

