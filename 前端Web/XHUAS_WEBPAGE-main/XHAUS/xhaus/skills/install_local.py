"""Install a local skill into ~/.xhaus/skills and wire all agent workspaces."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from xhaus.core.openclaw_agent import list_openclaw_agents, restart_openclaw_gateway
from xhaus.skills.openclaw_skills_config import ensure_allow_symlink_targets
from xhaus.skills.paths import (
    IGNORE_DIR_NAMES,
    SKILL_MD_FILENAME,
    bundled_skills_root,
    default_skills_root,
)
from xhaus.skills.workspace_link import link_skills_into_workspace

_CLOUD_HINT_RE = re.compile(
    r"^(https?://|git@|git:|github\.com|clawhub)",
    re.IGNORECASE,
)


@dataclass
class LocalSkillInstallResult:
    ok: bool
    skill_name: str
    dest: Path | None
    message: str = ""
    errors: list[str] | None = None
    warnings: list[str] | None = None


def is_cloud_skill_reference(value: str) -> bool:
    """True when input looks like ClawHub / Git URL (not a local folder)."""
    text = value.strip()
    if not text:
        return False
    if _CLOUD_HINT_RE.search(text):
        return True
    if "://" in text and not Path(text).expanduser().is_dir():
        return True
    return False


def cloud_skill_instructions() -> str:
    return """
云端 Skill（ClawHub / GitHub）请在 OpenClaw 应用已配置完成后，由 OpenClaw 自行安装：

  openclaw skills search <关键词>          # 搜索 ClawHub
  openclaw skills install <slug>         # 从 ClawHub 安装
  openclaw skills install git:<仓库URL>    # 从 Git 安装
  openclaw skills install --global <slug>  # 安装到共享目录

文档: https://docs.openclaw.ai/cli/skills

本脚本仅处理「本地自建 skill 目录」→ ~/.xhaus/skills 的安装。
""".strip()


def _copy_ignore(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n in IGNORE_DIR_NAMES or n.startswith(".")]


def _retry_remove(func, target: str, _exc) -> None:
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    func(target)


def _remove_existing(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        try:
            shutil.rmtree(path, onexc=_retry_remove)
        except TypeError:  # Python < 3.12
            shutil.rmtree(path, onerror=_retry_remove)
    else:
        try:
            path.chmod(0o700)
        except OSError:
            pass
        path.unlink()


def validate_local_skill_dir(path: Path | str) -> tuple[Path, list[str]]:
    """Resolve skill root; errors if SKILL.md missing."""
    from xhaus.cli.path_input import parse_path_input

    root = parse_path_input(str(path))
    errors: list[str] = []
    if not root.is_dir():
        return root, [f"不是有效目录: {root}"]
    skill_md = root / SKILL_MD_FILENAME
    if not skill_md.is_file():
        nested = list(root.glob(f"**/{SKILL_MD_FILENAME}"))
        if len(nested) == 1:
            root = nested[0].parent.resolve()
        else:
            errors.append(f"目录中缺少 {SKILL_MD_FILENAME}: {root}")
    return root, errors


def install_local_skill(
    source_dir: Path,
    *,
    force: bool = False,
    relink_agents: bool = True,
    restart_gateway: bool = True,
    patch_openclaw_config: bool = True,
) -> LocalSkillInstallResult:
    """
    1. Copy local skill project → ~/.xhaus/skills/<name>/
    2. Add trust roots to openclaw.json skills.load.allowSymlinkTargets
    3. Symlink skills into every configured agent workspace
    4. Optionally restart gateway
    """
    errors: list[str] = []
    warnings: list[str] = []

    root, validate_errors = validate_local_skill_dir(source_dir)
    if validate_errors:
        return LocalSkillInstallResult(
            ok=False,
            skill_name=root.name,
            dest=None,
            message="本地 skill 校验失败",
            errors=validate_errors,
        )

    skill_name = root.name
    shared_root = default_skills_root()
    shared_root.mkdir(parents=True, exist_ok=True)
    dest = shared_root / skill_name
    merge_existing_dir = False

    if dest.exists():
        if not force:
            return LocalSkillInstallResult(
                ok=False,
                skill_name=skill_name,
                dest=dest,
                message=f"目标已存在: {dest}（使用 --force 覆盖）",
                errors=[f"已存在: {dest}"],
            )
        if dest.is_dir() and not dest.is_symlink():
            merge_existing_dir = True
            warnings.append(f"覆盖模式：已合并更新已有目录 {dest}")
        else:
            try:
                _remove_existing(dest)
            except OSError as exc:
                return LocalSkillInstallResult(
                    ok=False,
                    skill_name=skill_name,
                    dest=dest,
                    message="覆盖旧 skill 失败",
                    errors=[f"无法删除旧目录 {dest}: {exc}"],
                )

    try:
        shutil.copytree(root, dest, ignore=_copy_ignore, dirs_exist_ok=merge_existing_dir)
    except OSError as exc:
        return LocalSkillInstallResult(
            ok=False,
            skill_name=skill_name,
            dest=None,
            message="复制失败",
            errors=[str(exc)],
        )

    if patch_openclaw_config:
        trust_roots = [shared_root, bundled_skills_root()]
        added, cfg_errors = ensure_allow_symlink_targets(trust_roots)
        errors.extend(cfg_errors)
        if added:
            warnings.append(
                "已在 openclaw.json 添加符号链接信任: " + ", ".join(added)
            )

    if relink_agents:
        agents = list_openclaw_agents()
        if not agents:
            warnings.append("未找到 OpenClaw Agent，跳过 workspace 链接")
        for agent in agents:
            link_result = link_skills_into_workspace(agent.workspace)
            warnings.extend(link_result.warnings)
            if link_result.errors:
                errors.extend(
                    f"[{agent.id}] {e}" for e in link_result.errors
                )
            elif link_result.linked and skill_name in link_result.linked:
                warnings.append(
                    f"已链接到 Agent {agent.id}: {agent.workspace}/skills/{skill_name}"
                )

    if restart_gateway and not errors:
        ok, msg = restart_openclaw_gateway()
        if ok:
            warnings.append(msg)
        else:
            warnings.append(f"Gateway 重启: {msg}")

    if errors:
        return LocalSkillInstallResult(
            ok=False,
            skill_name=skill_name,
            dest=dest,
            message="安装完成但存在错误",
            errors=errors,
            warnings=warnings,
        )

    return LocalSkillInstallResult(
        ok=True,
        skill_name=skill_name,
        dest=dest,
        message=f"已安装到共享目录: {dest}",
        warnings=warnings,
    )
