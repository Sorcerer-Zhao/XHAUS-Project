"""Interactive terminal menu (arrow keys + filled/empty square indicators)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# OpenClaw-style indicators: empty vs filled square
BOX_EMPTY = "□"
BOX_FILLED = "■"

_ARROW_UP = ("\x1b[A", "\x1bOA")
_ARROW_DOWN = ("\x1b[B", "\x1bOB")
_ENTER = ("\r", "\n")


@dataclass(frozen=True)
class MenuChoice:
    """One selectable menu row."""

    label: str
    value: str


def _supports_arrow_menu() -> bool:
    if os.environ.get("XHAUS_FORCE_ARROW_MENU") == "1":
        return True
    if os.environ.get("XHAUS_NO_ARROW_MENU") == "1":
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _read_key() -> str:
    """Read a single key or escape sequence from the terminal."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            code = ord(ch2)
            if code == 72:
                return "\x1b[A"
            if code == 80:
                return "\x1b[B"
        return ch

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = sys.stdin.read(1)
        if first != "\x1b":
            return first
        second = sys.stdin.read(1)
        if second != "[" and second != "O":
            return first + second
        third = sys.stdin.read(1)
        return first + second + third
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _render_block(
    choices: list[MenuChoice],
    index: int,
    *,
    title_lines: list[str],
    hint: str,
    previous_lines: int,
) -> int:
    if previous_lines > 0:
        sys.stdout.write(f"\033[{previous_lines}A")

    lines: list[str] = list(title_lines)
    for i, choice in enumerate(choices):
        box = BOX_FILLED if i == index else BOX_EMPTY
        lines.append(f"  {box}  {choice.label}")
    if hint:
        lines.append("")
        lines.append(f"  {hint}")

    for line in lines:
        sys.stdout.write("\033[K")
        sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return len(lines)


def _select_arrow(choices: list[MenuChoice], *, title_lines: list[str], hint: str) -> MenuChoice:
    if not choices:
        raise ValueError("menu requires at least one choice")

    index = 0
    hint_text = hint or "↑↓ 切换选项 · Enter 确认"
    line_count = 0

    while True:
        line_count = _render_block(
            choices,
            index,
            title_lines=title_lines,
            hint=hint_text,
            previous_lines=line_count,
        )
        key = _read_key()
        if key in _ARROW_UP:
            index = (index - 1) % len(choices)
        elif key in _ARROW_DOWN:
            index = (index + 1) % len(choices)
        elif key in _ENTER:
            break
        elif key == "\x03":
            raise KeyboardInterrupt

    # Leave final frame visible
    _render_block(
        choices,
        index,
        title_lines=title_lines,
        hint=f"已选择: {choices[index].label}",
        previous_lines=line_count,
    )
    print()
    return choices[index]


def _select_fallback(choices: list[MenuChoice], *, title_lines: list[str], hint: str) -> MenuChoice:
    """Numbered fallback when stdin is not a TTY (pipes, CI)."""
    for line in title_lines:
        print(line)
    print()
    for i, choice in enumerate(choices, start=1):
        print(f"  {BOX_EMPTY}  [{i}] {choice.label}")
    if hint:
        print()
        print(f"  {hint}")
    print()

    from xhaus.cli.validators import validate_menu_choice

    while True:
        raw = input("请输入选项编号: ").strip()
        ok, msg = validate_menu_choice(raw, max_option=len(choices))
        if ok:
            return choices[int(raw) - 1]
        print(f"  ⚠ {msg}")


def select_menu(
    choices: list[MenuChoice],
    *,
    title: str | None = None,
    hint: str | None = None,
) -> MenuChoice:
    """
    Show an interactive menu. Arrow keys move selection; Enter confirms.
    Falls back to numbered input when not attached to a terminal.
    """
    title_lines: list[str] = []
    if title:
        title_lines.append(title)

    if _supports_arrow_menu():
        try:
            return _select_arrow(choices, title_lines=title_lines, hint=hint or "")
        except (ImportError, OSError):
            pass

    return _select_fallback(choices, title_lines=title_lines, hint=hint or "")
