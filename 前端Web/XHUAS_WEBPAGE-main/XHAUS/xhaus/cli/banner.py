"""XHAUS CLI banner and introduction."""

from __future__ import annotations

import os
import sys

from xhaus import __title__, __version__

ASCII_BANNER = r"""
 __  __  _   _     _     _   _   ____
 \ \/ / | | | |   / \   | | | | / ___|
  \  /  | |_| |  / _ \  | | | | \___ \
  /  \  |  _  | / ___ \ | |_| | ___) |
 /_/\_\ |_| |_|/_/   \_\ \___/ |____/
""".strip("\n")

INTRO_TEXT = """
XHAUS — Persona & Skills Runtime Bridge

XHAUS 不是聊天客户端，也不是 Agent 本体或推理层。
它是连接 OpenClaw WebSocket Runtime 的中转框架，
负责挂载人格（Profile）与技能（Skills）配置。

本轮向导将帮助你完成基础设置，并在连接畅通后进入控制台对话。
""".strip()


def print_banner() -> None:
    print(ASCII_BANNER)
    if _use_color():
        print(f"\033[2m  {__title__} v{__version__}\033[0m")
    else:
        print(f"  {__title__} v{__version__}")
    print()


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()
