"""CLI wizard — install a local skill into ~/.xhaus/skills."""

from __future__ import annotations

import sys
from pathlib import Path

from xhaus.cli.path_input import parse_path_input
from xhaus.cli.prompts import ask, ask_confirm, print_step
from xhaus.skills.install_local import (
    cloud_skill_instructions,
    install_local_skill,
    is_cloud_skill_reference,
    validate_local_skill_dir,
)
from xhaus.skills.paths import SKILL_MD_FILENAME, default_skills_root

WIZARD_STEPS = 3


def _validate_skill_path(value: str) -> tuple[bool, str]:
    raw = value.strip()
    if not raw:
        return False, "路径不能为空。"
    if is_cloud_skill_reference(raw):
        return False, "这是云端地址。ClawHub/Git 请用: openclaw skills install <slug>"
    root, errors = validate_local_skill_dir(raw)
    if errors:
        return False, errors[0]
    return True, str(root)


def run_install_skill_wizard() -> int:
    shared = default_skills_root()

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  XHAUS · 安装本地 Skill                  ║")
    print("  ╚══════════════════════════════════════════╝")

    print_step(1, WIZARD_STEPS, "说明")
    print("  本向导将把你电脑上的 skill 项目**复制**到共享目录：")
    print(f"    {shared}/<skill名>/")
    print()
    print("  复制后，所有 OpenClaw 管家可通过符号链接使用该 skill。")
    print()
    print("  云端 Skill（ClawHub / GitHub）不在此处理，请配置 OpenClaw 后执行：")
    print("    openclaw skills install <slug>")
    print()

    print_step(2, WIZARD_STEPS, "Skill 项目目录")
    print("  请输入本地 skill 文件夹路径（根目录须含 SKILL.md）。")
    print("  示例: ~/projects/my-skill  或  ./Satellite")
    print()

    cwd = Path.cwd()
    default_path = str(cwd) if (cwd / SKILL_MD_FILENAME).is_file() else None

    source_str = ask(
        "项目目录",
        default=default_path,
        validator=_validate_skill_path,
        hint="可拖入文件夹（自动去除引号）",
    )
    source = parse_path_input(source_str)
    skill_name = source.name
    dest = shared / skill_name

    print()
    print(f"  已选择: {skill_name}")
    print(f"  来源  : {source}")
    print(f"  目标  : {dest}")
    print()

    force = False
    if dest.exists():
        print(f"  ℹ 共享目录中已存在: {dest}")
        force = ask_confirm("是否覆盖并重新安装？", default_yes=False)

    print_step(3, WIZARD_STEPS, "复制并同步")
    print("  正在复制到 ~/.xhaus/skills …")
    print()

    result = install_local_skill(
        source,
        force=force,
        relink_agents=True,
        restart_gateway=True,
        patch_openclaw_config=True,
    )

    print("  ── 完成 ──")
    print()
    if result.ok:
        print(f"  ✓ {result.message}")
        print(f"  · Skill 名 : {result.skill_name}")
        if result.dest:
            print(f"  · 共享路径 : {result.dest}")
    else:
        print(f"  ✗ {result.message or '安装失败'}", file=sys.stderr)

    if result.warnings:
        print()
        print("  提示:")
        for note in result.warnings:
            print(f"    · {note}")

    if result.errors:
        print()
        print("  问题:")
        for err in result.errors:
            print(f"    · {err}", file=sys.stderr)

    if not result.ok:
        return 1

    print()
    print("  下一步: 重新进入 XHAUS 向导对话，或确认各管家 workspace 已链接该 skill。")
    print()
    return 0
