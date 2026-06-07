"""Terminal loading spinner for blocking waits."""

from __future__ import annotations

import sys
import threading
import time


class LoadingSpinner:
    """Animated spinner; falls back to static text when stdout is not a TTY."""

    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, message: str = "正在连接…") -> None:
        self._message = message
        self._detail = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._use_tty = sys.stdout.isatty()

    def set_detail(self, detail: str) -> None:
        self._detail = detail.strip()

    def __enter__(self) -> LoadingSpinner:
        if not self._use_tty:
            print(f"  {self._message}")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._use_tty:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _run(self) -> None:
        index = 0
        while not self._stop.is_set():
            frame = self._FRAMES[index % len(self._FRAMES)]
            line = f"{frame} {self._message}"
            if self._detail:
                short = self._detail if len(self._detail) <= 48 else self._detail[:45] + "…"
                line = f"{line}  ({short})"
            sys.stdout.write(f"\r{line}")
            sys.stdout.flush()
            index += 1
            time.sleep(0.08)
