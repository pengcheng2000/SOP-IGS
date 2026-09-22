from __future__ import annotations

import json
import sys
from pathlib import Path

from .com_finalizer import finalize_with_word

if __name__ == "__main__":
    print(json.dumps(finalize_with_word(Path(sys.argv[1])), ensure_ascii=False))

