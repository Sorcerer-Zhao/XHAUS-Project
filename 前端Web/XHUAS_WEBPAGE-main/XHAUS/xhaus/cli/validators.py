"""Input validators for the CLI wizard."""

from __future__ import annotations

import re
from urllib.parse import urlparse

ROLE_CUSTOM = "custom"
ROLE_CUSTOM_PROFILE_PREFIX = "custom:"

PROFILE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_websocket_url(value: str) -> tuple[bool, str]:
    """
    Basic WebSocket URL check (no live connection).
    Accepts ws:// or wss:// with host; port optional.
    """
    raw = value.strip()
    if not raw:
        return False, "地址不能为空，请输入 OpenClaw 的 WebSocket 地址。"

    parsed = urlparse(raw)
    if parsed.scheme not in ("ws", "wss"):
        return False, "地址须以 ws:// 或 wss:// 开头，例如 wss://127.0.0.1:18789"

    if not parsed.netloc:
        return False, "地址格式无效：缺少主机名或 IP。"

    host = parsed.hostname
    if not host:
        return False, "地址格式无效：无法解析主机。"

    if " " in raw:
        return False, "地址中不能包含空格。"

    return True, raw


def validate_menu_choice(value: str, *, max_option: int) -> tuple[bool, str]:
    raw = value.strip()
    if not raw:
        return False, "请输入选项编号。"
    if not raw.isdigit():
        return False, f"请输入 1 到 {max_option} 之间的数字。"
    choice = int(raw)
    if choice < 1 or choice > max_option:
        return False, f"无效选项：请输入 1 到 {max_option}。"
    return True, raw


def validate_profile_name(value: str) -> tuple[bool, str]:
    raw = value.strip()
    if not raw:
        return False, "角色名称不能为空。"
    if not PROFILE_NAME_PATTERN.match(raw):
        return False, "名称仅允许字母、数字、下划线与连字符，长度 1–64。"
    if raw.startswith(".") or raw.startswith("-"):
        return False, "名称不能以 . 或 - 开头。"
    return True, raw


def validate_confirm(value: str) -> tuple[bool, bool]:
    """Parse y/n style confirmation. Returns (ok, accepted)."""
    raw = value.strip().lower()
    if raw in ("y", "yes", "是", "好", "确定"):
        return True, True
    if raw in ("n", "no", "否", "不"):
        return True, False
    return False, False
