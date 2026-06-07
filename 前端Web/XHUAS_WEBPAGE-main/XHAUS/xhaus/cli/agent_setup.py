"""Wizard step — create or bind an OpenClaw Agent for a custom profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xhaus.cli.menu import MenuChoice, select_menu
from xhaus.cli.prompts import ask, ask_confirm, ask_secret, iprint, print_subsection
from xhaus.core.openclaw_agent import (
    DEEPSEEK_PROVIDER,
    DEFAULT_MODEL,
    default_openclaw_workspace,
    list_openclaw_agents,
    normalize_openclaw_agent_id,
    provision_agent_for_profile,
)


@dataclass
class AgentSetupResult:
    agent_id: str | None
    errors: list[str]
    warnings: list[str]


def validate_agent_id(value: str) -> tuple[bool, str]:
    raw = value.strip()
    if not raw:
        return False, "Agent ID 不能为空。"
    normalized = normalize_openclaw_agent_id(raw)
    if not normalized:
        return False, "Agent ID 无效。"
    return True, normalized


def _prompt_agent_mode(*, indent: int) -> str:
    print_subsection("OpenClaw Agent", indent=indent)
    iprint("只需创建 Agent 并同步 Profile 文档，无需其他 OpenClaw 配置。", indent=indent)
    iprint("Session 路由: agent:<id>:main", indent=indent)
    print()
    selected = select_menu(
        [
            MenuChoice("创建新的 OpenClaw Agent", "create"),
            MenuChoice("绑定已有 Agent", "existing"),
        ],
        title=f"{'\t' * indent}  请选择：",
        hint="↑↓ 切换 · Enter 确认",
    )
    return selected.value


def _select_existing_agent(*, indent: int) -> str | None:
    agents = list_openclaw_agents()
    if not agents:
        iprint("⚠ 未找到已有 Agent，请先创建或检查 openclaw CLI。", indent=indent)
        return None

    choices = [
        MenuChoice(
            f"{a.id}"
            + (f" ({a.name})" if a.name else "")
            + f" — {a.workspace}",
            a.id,
        )
        for a in agents
    ]
    selected = select_menu(
        choices,
        title=f"{'\t' * indent}  选择要绑定的 Agent：",
        hint="↑↓ 切换 · Enter 确认",
    )
    return selected.value


def _maybe_prompt_deepseek_api_key(*, indent: int) -> str | None:
    print_subsection("模型 API（可选）", indent=indent)
    iprint(f"供应商: {DEEPSEEK_PROVIDER} · 模型: {DEFAULT_MODEL}", indent=indent)
    iprint("创建 Agent 本身不需要 API Key；可稍后用 openclaw models auth 配置。", indent=indent)
    print()
    if not ask_confirm("现在配置 DeepSeek API Key？", default_yes=False, indent=indent):
        return None
    return ask_secret("DeepSeek API Key", indent=indent)


def setup_openclaw_agent_for_profile(
    profile_name: str,
    profile_dir: Path,
    *,
    indent: int = 1,
    force_create: bool = False,
) -> AgentSetupResult:
    """
    1. openclaw agents add <id> --workspace ~/.openclaw/workspace-<id> --model ...
    2. 将 profile_dir 四文档拷贝到该 workspace
    3. openclaw gateway restart
    """
    mode = "create" if force_create else _prompt_agent_mode(indent=indent)
    errors: list[str] = []
    warnings: list[str] = []
    agent_id: str | None = None
    model = DEFAULT_MODEL
    api_key: str | None = None
    workspace: Path | None = None

    if mode == "create":
        print_subsection("新建 Agent", indent=indent)
        agent_id = ask(
            "Agent 名字",
            default=normalize_openclaw_agent_id(profile_name),
            validator=validate_agent_id,
            hint="回车即用默认；OpenClaw 会规范为小写，如 Toru → toru",
            indent=indent,
        )
        workspace = default_openclaw_workspace(agent_id)
        iprint("将执行:", indent=indent)
        iprint(
            f"openclaw agents add {agent_id} \\",
            indent=indent,
        )
        iprint(f"  --workspace {workspace} \\", indent=indent)
        iprint(f"  --model {model} --non-interactive", indent=indent)
        print()
        api_key = _maybe_prompt_deepseek_api_key(indent=indent)
    else:
        print_subsection("绑定已有 Agent", indent=indent)
        agent_id = _select_existing_agent(indent=indent)
        if not agent_id:
            return AgentSetupResult(None, ["未选择 OpenClaw Agent"], [])

    print_subsection("同步 Profile 与 Skills", indent=indent)
    iprint(f"Profile 来源: {profile_dir}", indent=indent)
    iprint("→ 拷贝 IDENTITY / SOUL / AGENTS / USER 到 Agent 工作区", indent=indent)
    iprint("→ 符号链接 templates/skills 与 ~/.xhaus/skills 到 workspace/skills", indent=indent)
    print()

    result = provision_agent_for_profile(
        profile_name=profile_name,
        profile_dir=profile_dir,
        mode=mode,
        agent_id=agent_id,
        workspace=workspace,
        model=model,
        deepseek_api_key=api_key,
        restart_gateway=True,
    )

    if result.message:
        iprint(f"✓ {result.message}", indent=indent)
    if result.workspace:
        iprint(f"· 工作区: {result.workspace}", indent=indent)
    iprint(f"· Agent ID: {result.agent_id}", indent=indent)
    iprint(f"· Session : agent:{result.agent_id}:main", indent=indent)

    if result.warnings:
        warnings.extend(result.warnings)
        for note in result.warnings:
            iprint(f"· {note}", indent=indent)

    if result.errors:
        errors.extend(result.errors)
        for err in result.errors:
            iprint(f"⚠ {err}", indent=indent)

    if not result.ok:
        return AgentSetupResult(None, errors or ["OpenClaw Agent 配置失败"], warnings)

    return AgentSetupResult(result.agent_id, errors, warnings)
