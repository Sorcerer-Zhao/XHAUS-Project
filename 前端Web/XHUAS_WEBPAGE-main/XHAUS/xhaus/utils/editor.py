"""Open files in the user's preferred editor."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_editor_command() -> list[str] | None:
    """Return editor argv, or None if no editor is available."""
    if sys.platform == "win32":
        return ["notepad.exe"]

    if sys.platform == "darwin" and shutil.which("open"):
        return ["open", "-W", "-a", "TextEdit"]

    editor = os.environ.get("EDITOR", "").strip()
    if editor:
        return editor.split()

    for name in ("nano", "vim", "vi"):
        if shutil.which(name):
            return [name]
    return None


def open_in_editor(path: Path) -> tuple[bool, str]:
    """
    Open path in editor and wait until the user closes it.
    Returns (success, message).
    """
    path = path.resolve()
    if not path.parent.is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)

    if not path.is_file():
        path.touch()

    cmd = resolve_editor_command()
    if not cmd:
        return False, (
            "未找到可用编辑器。请设置环境变量 EDITOR，"
            "或安装 nano / vim。"
        )

    argv = [*cmd, str(path)]
    try:
        subprocess.run(argv, check=False)
    except OSError as exc:
        return False, f"无法启动编辑器 ({' '.join(argv)}): {exc}"

    return True, str(path)
