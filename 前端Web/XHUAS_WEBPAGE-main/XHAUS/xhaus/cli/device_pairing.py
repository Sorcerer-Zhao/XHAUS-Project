"""CLI guide for OpenClaw device pairing before console chat."""

from __future__ import annotations

from xhaus.cli.prompts import print_step
from xhaus.core.device_pairing import (
    build_approve_command,
    device_identity_status,
    pairing_explanation,
    try_approve_pending_device,
)


def run_device_pairing_guide(
    websocket_url: str,
    *,
    token: str | None = None,
    step: int = 6,
    total_steps: int = 7,
) -> None:
    """
    Explain pairing and attempt ``openclaw devices approve --latest``.

    Call when chat connect fails with pairing required; then retry connect.
    """
    print_step(step, total_steps, "设备配对")
    print(pairing_explanation())
    print()

    has_identity, identity_path = device_identity_status()
    if has_identity:
        print(f"  ✓ 已找到设备身份: {identity_path}")
    else:
        print(f"  ⚠ 未找到设备身份: {identity_path}")
        print("    请先在本机安装 OpenClaw CLI，并确保 Gateway 可访问。")
    print()

    print("  正在尝试自动批准本机设备…")
    ok, msg = try_approve_pending_device(websocket_url, token=token)
    if ok:
        print(f"  ✓ {msg}")
        print()
        return

    print(f"  ⚠ 自动批准未成功: {msg}")
    print()
    print("  请在【运行 Gateway 的机器】上手动执行：")
    print()
    print(f"    {build_approve_command(websocket_url, token=token)}")
    print()
    print("  或查看待批准列表：")
    print(f"    openclaw devices list --url {websocket_url}")
    print()
    input("  已在 Gateway 侧批准设备后，按 Enter 继续重试连接… ")
