"""OpenClaw Gateway device pairing — detect errors and auto-approve when possible."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from xhaus.core.connector.device_identity import load_device_identity, openclaw_state_dir

logger = logging.getLogger(__name__)


class PairingRequiredError(Exception):
    """Raised when chat connect needs device approval before retrying."""


def is_pairing_required_error(message: str) -> bool:
    text = (message or "").lower()
    return "pairing required" in text or "not approved" in text


def pairing_explanation() -> str:
    return """
设备配对（pairing）不是 WSL 或 Windows 适配 bug，而是 OpenClaw Gateway 的安全机制：

  · 每台电脑 / 每个用户目录会生成一份「设备身份」(~/.openclaw/identity/device.json)
  · 控制台对话使用 cli 模式连接，Gateway 会把 XHAUS 视为一台「新设备」
  · 第一次连接时，Gateway 要求管理员批准，未批准则报 pairing required

步骤 5「挂载」往往仍能通过（仅用 Gateway Token 预检）；
步骤 6「对话」才必须完成设备配对。

若 Gateway 在另一台机器或 WSL 宿主机上，请确保 WebSocket 地址可达，
并在能管理 Gateway 的那一侧执行批准命令。
""".strip()


def build_approve_command(websocket_url: str, *, token: str | None = None) -> str:
    parts = ["openclaw", "devices", "approve", "--latest", "--url", websocket_url]
    if token:
        parts.extend(["--token", token])
    return " ".join(parts)


def try_approve_pending_device(
    websocket_url: str,
    *,
    token: str | None = None,
    timeout_s: float = 30.0,
) -> tuple[bool, str]:
    """Run ``openclaw devices approve --latest`` if CLI is available."""
    if shutil.which("openclaw") is None:
        return False, "未找到 openclaw 命令，请手动批准设备"

    cmd = [
        "openclaw",
        "devices",
        "approve",
        "--latest",
        "--url",
        websocket_url,
        "--timeout",
        str(int(timeout_s * 1000)),
    ]
    if token:
        cmd.extend(["--token", token])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s + 5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"执行批准命令失败: {exc}"

    if proc.returncode == 0:
        out = (proc.stdout or proc.stderr or "").strip()
        return True, out or "设备已批准"

    err = (proc.stderr or proc.stdout or "unknown error").strip()
    return False, err


def device_identity_status() -> tuple[bool, Path]:
    root = openclaw_state_dir()
    identity = load_device_identity(root)
    path = root / "identity" / "device.json"
    return identity is not None, path
