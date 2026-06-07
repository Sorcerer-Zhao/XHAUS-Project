"""CLI setup wizard — interactive onboarding flow."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from xhaus.cli.agent_setup import setup_openclaw_agent_for_profile
from xhaus.cli.banner import INTRO_TEXT, print_banner
from xhaus.cli.custom_profile import (
    custom_profile_dir,
    edit_profile_documents,
    ensure_custom_profile,
)
from xhaus.cli.menu import select_menu
from xhaus.cli.presets import (
    is_saved_custom_profile,
    saved_custom_profile_name,
    scan_preset_choices,
)
from xhaus.cli.prompts import ask, ask_confirm, print_step
from xhaus.cli.validators import (
    ROLE_CUSTOM,
    validate_profile_name,
    validate_websocket_url,
)
from xhaus.config import load_from_directory, load_preset
from xhaus.config.paths import default_custom_profiles_root, presets_root
from xhaus.cli.chat import run_console_chat
from xhaus.core.activation import activate_xhaus, resolve_gateway_token
from xhaus.core.openclaw_agent import (
    find_agent_for_preset,
    normalize_openclaw_agent_id,
    reuse_agent_with_profile,
)

WIZARD_STEPS = 7


@dataclass
class WizardResult:
    """Collected wizard inputs (no runtime connection yet)."""

    websocket_url: str
    role_label: str
    preset_name: str | None
    profile_path: Path | None
    documents_ok: bool
    agent_configured: bool
    profile_ok: bool
    profile_errors: list[str]
    profile_warnings: list[str] = field(default_factory=list)
    agent_id: str = "hausmeister"


def _prompt_websocket() -> str:
    print_step(1, WIZARD_STEPS, "连接 OpenClaw Runtime")
    print("  请输入 OpenClaw 的 WebSocket 地址。")
    print("  示例: wss://127.0.0.1:18789 或 ws://localhost:18789")
    print("  同一 Gateway 可服务多个 Agent；对话时由 Agent ID 区分。")
    print()
    return ask(
        "WebSocket 地址",
        validator=validate_websocket_url,
        hint="须以 ws:// 或 wss:// 开头",
    )


def _prompt_role() -> tuple[str, str]:
    """Return (display_label, preset_key_or_ROLE_CUSTOM)."""
    print_step(2, WIZARD_STEPS, "选择角色")

    choices = scan_preset_choices()
    if len(choices) <= 1:
        print(f"  ⚠ 未在预设目录找到角色: {presets_root()}")
        print("  仅可选择「自定义角色」。请向 presets/ 添加包含 Profile 文档的文件夹。")
        print()

    selected = select_menu(
        choices,
        title="  请选择一个 Persona Profile：",
        hint="↑↓ 切换 · Enter 确认",
    )
    return selected.label, selected.value


def _setup_custom_role() -> tuple[Path, str, list[str]]:
    print_step(3, WIZARD_STEPS, "自定义角色")
    print("  将创建或打开自定义 Profile 目录，并依次编辑四个文档：")
    for name in ("IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md"):
        print(f"    · {name}")
    print()
    print(f"  默认保存位置: {default_custom_profiles_root()}/<角色名>/")
    print()

    name = ask("自定义角色名称", validator=validate_profile_name)
    dest = custom_profile_dir(name)
    errors: list[str] = []

    if dest.is_dir() and any(dest.iterdir()):
        print(f"  ℹ 目录已存在: {dest}")
        if not ask_confirm("是否继续使用该目录并编辑文档？", default_yes=True):
            return dest, name, ["用户取消了自定义角色编辑"]
    else:
        dest, created = ensure_custom_profile(name)
        if created:
            print(f"  ✓ 已从模板创建: {dest}")

    edit_errors = edit_profile_documents(dest)
    errors.extend(edit_errors)
    return dest, name, errors


def _load_saved_custom_profile(role_key: str) -> tuple[Path, str]:
    profile_name = saved_custom_profile_name(role_key)
    path = custom_profile_dir(profile_name)
    print_step(3, WIZARD_STEPS, "已有自定义角色")
    print(f"  已选择: {profile_name}")
    print(f"  Profile 路径: {path}")
    print()
    return path, profile_name


def _run_agent_setup(
    profile_name: str,
    profile_dir: Path,
    *,
    force_create: bool = False,
) -> tuple[str | None, list[str], list[str]]:
    print_step(4, WIZARD_STEPS, "OpenClaw Agent")
    print("  以下为 Agent 配置（隶属于步骤 4）")
    print()
    setup = setup_openclaw_agent_for_profile(
        profile_name,
        profile_dir,
        indent=1,
        force_create=force_create,
    )
    return setup.agent_id, setup.errors, setup.warnings


def _resolve_preset_agent(
    preset_name: str,
    preset_dir: Path,
    role_label: str,
) -> tuple[str | None, list[str], list[str]]:
    print_step(4, WIZARD_STEPS, "OpenClaw Agent")

    existing = find_agent_for_preset(preset_name, preset_dir)
    if existing is not None:
        print(f"  已检测到承载「{role_label}」的 OpenClaw Agent: {existing.id}")
        print(f"  工作区: {existing.workspace}")
        print("  将同步预设 Profile 并继续连接。")
        print()
        result = reuse_agent_with_profile(existing, preset_dir)
        errors = list(result.errors)
        warnings: list[str] = []
        if result.message:
            print(f"  ✓ {result.message}")
        if errors:
            for err in errors:
                print(f"  ⚠ {err}")
        else:
            print(f"  · Agent ID: {result.agent_id}")
            print(f"  · Session : agent:{result.agent_id}:main")
        print()
        if not result.ok:
            return None, errors or ["Profile 同步失败"], warnings
        return result.agent_id, errors, warnings

    print(f"  您目前 OpenClaw 当中还没有一个 Agent 应用供「{role_label}」去使用，")
    print("  现在引导您进行创建。")
    print()
    return _run_agent_setup(preset_name, preset_dir, force_create=True)


def _resolve_profile(
    role_key: str,
    *,
    role_label: str,
) -> tuple[str | None, Path | None, str | None, bool, bool, list[str], list[str], str | None]:
    """Returns preset, path, profile_name, documents_ok, agent_configured, errors, warnings, agent_id."""
    preset: str | None = None
    path: Path | None = None
    profile_name: str | None = None
    agent_id: str | None = None
    extra_errors: list[str] = []
    extra_warnings: list[str] = []

    if role_key == ROLE_CUSTOM:
        path, profile_name, extra_errors = _setup_custom_role()
        if extra_errors and any("取消" in e or "中止" in e for e in extra_errors):
            return None, path, profile_name, False, False, extra_errors, [], None
        result = load_from_directory(path)
        if result.warnings:
            extra_warnings.extend(result.warnings)
        if result.ok and profile_name and path:
            agent_id, agent_errors, agent_warnings = _run_agent_setup(
                profile_name, path
            )
            extra_errors.extend(agent_errors)
            extra_warnings.extend(agent_warnings)
    elif is_saved_custom_profile(role_key):
        path, profile_name = _load_saved_custom_profile(role_key)
        result = load_from_directory(path)
        if result.warnings:
            extra_warnings.extend(result.warnings)
        if result.ok and path.is_dir():
            agent_id, agent_errors, agent_warnings = _run_agent_setup(
                profile_name, path
            )
            extra_errors.extend(agent_errors)
            extra_warnings.extend(agent_warnings)
    else:
        preset = role_key
        result = load_preset(preset)
        if result.warnings:
            extra_warnings.extend(result.warnings)
        if result.ok and result.profile is not None:
            agent_id, agent_errors, agent_warnings = _resolve_preset_agent(
                preset,
                result.profile.base_path,
                role_label,
            )
            extra_errors.extend(agent_errors)
            extra_warnings.extend(agent_warnings)
        elif result.ok:
            extra_errors.append("预设 Profile 路径未知，无法配置 OpenClaw Agent")

    doc_errors = list(result.errors)
    agent_errors = list(extra_errors)
    errors = doc_errors + agent_errors
    warnings = extra_warnings
    documents_ok = result.ok and not doc_errors
    agent_configured = agent_id is not None and not agent_errors
    profile_ok = documents_ok and agent_configured
    if not agent_configured and not any("取消" in e for e in agent_errors):
        agent_errors.append("OpenClaw Agent 未配置成功")
        errors.append(agent_errors[-1])

    return preset, path, profile_name, documents_ok, agent_configured, errors, warnings, agent_id


def _run_activation(result: WizardResult) -> None:
    print_step(5, WIZARD_STEPS, "挂载与激活")
    print()

    if not result.profile_ok:
        if not result.documents_ok:
            print("  ⚠ Profile 四文档未完整，跳过 WebSocket 挂载。")
        elif not result.agent_configured:
            print("  ⚠ OpenClaw Agent 未配置，跳过 WebSocket 挂载。")
        else:
            print("  ⚠ 配置未就绪，跳过 WebSocket 挂载。")
        for err in result.profile_errors:
            print(f"    · {err}")
        print()
        return

    activation = activate_xhaus(
        websocket_url=result.websocket_url,
        preset_name=result.preset_name,
        profile_path=result.profile_path,
        role_label=result.role_label,
        profile_ok=result.profile_ok,
        profile_errors=result.profile_errors,
        agent_id=result.agent_id,
    )
    print()
    print(activation.report())
    print()

    if activation.ok and os.environ.get("XHAUS_SKIP_CONSOLE_CHAT") == "1":
        print_step(6, WIZARD_STEPS, "控制台对话")
        print("  网页/小程序模式已启用：跳过 CLI 控制台对话。")
        print("  请在前端对话窗口继续与当前 Agent 交互。")
        print()
        return

    if activation.ok:
        _run_console_chat(result)


def _run_console_chat(result: WizardResult) -> None:
    print_step(6, WIZARD_STEPS, "控制台对话")
    run_console_chat(
        result.websocket_url,
        agent_id=result.agent_id,
        token=resolve_gateway_token(),
    )


def _print_summary(result: WizardResult) -> None:
    print_step(7, WIZARD_STEPS, "完成")
    print("  向导设置摘要")
    print()
    print(f"  WebSocket 地址 : {result.websocket_url}")
    print(f"  角色           : {result.role_label}")
    if result.preset_name:
        print(f"  预设 ID        : {result.preset_name}")
    if result.profile_path:
        print(f"  Profile 路径   : {result.profile_path}")
    doc_status = "完整 ✓" if result.documents_ok else "不完整"
    agent_status = f"{result.agent_id} ✓" if result.agent_configured else "未配置"
    print(f"  Profile 文档   : {doc_status}")
    print(f"  OpenClaw Agent : {agent_status}")
    if result.agent_configured:
        print(f"  Session Key    : agent:{result.agent_id}:main")
    print()
    if result.profile_warnings:
        print("  提示：")
        for warn in result.profile_warnings:
            print(f"    · {warn}")
        print()
    if result.profile_errors:
        print("  待处理问题：")
        for err in result.profile_errors:
            print(f"    · {err}")
        print()
    print("  ─────────────────────────────────────")
    print("  XHAUS 向导结束。")
    print()


def run_wizard() -> WizardResult:
    """Run the full interactive CLI wizard."""
    print_banner()
    print(INTRO_TEXT)
    print()

    websocket_url = _prompt_websocket()
    role_label, role_key = _prompt_role()

    if role_key not in (ROLE_CUSTOM,) and not is_saved_custom_profile(role_key):
        print()
        print("  （预设角色已就绪，跳过步骤 3 文档编辑）")
    elif is_saved_custom_profile(role_key):
        print()
        print("  （使用 ~/.xhaus/profiles 中已保存的角色）")

    (
        preset_name,
        profile_path,
        profile_name,
        documents_ok,
        agent_configured,
        profile_errors,
        profile_warnings,
        resolved_agent,
    ) = _resolve_profile(role_key, role_label=role_label)
    profile_ok = documents_ok and agent_configured

    agent_id = resolved_agent or (
        normalize_openclaw_agent_id(profile_name) if profile_name else "hausmeister"
    )

    if role_key not in (ROLE_CUSTOM,) and not is_saved_custom_profile(role_key):
        preset_name = role_key

    wizard_result = WizardResult(
        websocket_url=websocket_url,
        role_label=role_label,
        preset_name=preset_name,
        profile_path=profile_path,
        documents_ok=documents_ok,
        agent_configured=agent_configured,
        profile_ok=profile_ok,
        profile_errors=profile_errors,
        profile_warnings=profile_warnings,
        agent_id=agent_id,
    )
    _run_activation(wizard_result)
    _print_summary(wizard_result)
    return wizard_result
