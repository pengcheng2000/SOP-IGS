from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class WordProcessError(RuntimeError):
    code = "WORD_COM_FAILED"


def finalize_with_word(
    path: Path, timeout_seconds: int, heartbeat, *, module="app.boost.docx.word"
) -> dict:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # The child's output goes to temporary files, not pipes: a Windows pipe holds only 4 KB and the child
    # blocks on exit when the heading report is larger, while this loop only polls. Output is UTF-8 because
    # heading text may contain any Unicode character.
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        process = subprocess.Popen(
            [sys.executable, "-m", module, str(path.resolve())],
            stdout=out_file,
            stderr=err_file,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            cwd=str(Path(__file__).resolve().parents[2]),
            creationflags=creation_flags,
        )
        started = time.monotonic()
        while process.poll() is None and time.monotonic() - started < timeout_seconds:
            heartbeat(round(time.monotonic() - started))
            time.sleep(1)
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                )
            else:
                process.kill()
            raise WordProcessError(f"Word COM 超过 {timeout_seconds} 秒未完成")
        out_file.seek(0)
        err_file.seek(0)
        stdout = out_file.read().decode("utf-8", errors="replace")
        stderr = err_file.read().decode("utf-8", errors="replace")
    if process.returncode:
        raise WordProcessError((stderr or stdout or "Word COM 子进程失败").strip())
    try:
        return json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise WordProcessError("Word COM 未返回有效验证结果") from exc
