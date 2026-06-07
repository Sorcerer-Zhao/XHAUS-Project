"""Link bundled/user skills into an OpenClaw agent workspace."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from xhaus.skills.paths import IGNORE_DIR_NAMES, resolve_skills_roots
from xhaus.skills.scanner import discover_skill_files, skill_directory

WORKSPACE_SKILLS_DIR = "skills"


@dataclass
class SkillsLinkResult:
    linked: list[str]
    warnings: list[str]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _same_target(link: Path, target: Path) -> bool:
    try:
        return link.is_symlink() and link.resolve() == target.resolve()
    except OSError:
        return False


def _copy_ignore(_dir: str, names: list[str]) -> list[str]:
    return [name for name in names if name in IGNORE_DIR_NAMES or name.startswith(".")]


def _newest_mtime(root: Path) -> float:
    newest = 0.0
    for item in root.rglob("*"):
        try:
            if item.is_file():
                newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    return newest


def _copy_skill_dir(source: Path, target: Path) -> None:
    if target.exists():
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            source_newest = _newest_mtime(source)
            target_newest = _newest_mtime(target)
            if target_newest >= source_newest:
                return
            shutil.rmtree(target)
        else:
            target.unlink()
    shutil.copytree(source, target, ignore=_copy_ignore)


def link_skills_into_workspace(
    workspace: Path,
    *,
    include_bundled: bool = True,
    include_user: bool = True,
    extra_roots: list[Path | str] | None = None,
) -> SkillsLinkResult:
    """
    Put skill packages into ``<workspace>/skills/<name>``.

    OpenClaw loads skills from the agent workspace; this points each entry at
    ``xhaus/templates/skills`` and ``~/.xhaus/skills`` when symlinks are allowed.
    On Windows without symlink privileges, it falls back to copying the skill
    directory so frontend installation still works for normal users. First root
    wins when the same skill folder name appears in multiple roots.
    """
    linked: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    workspace = workspace.expanduser().resolve()
    skills_dest = workspace / WORKSPACE_SKILLS_DIR

    try:
        skills_dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return SkillsLinkResult([], [], [f"无法创建 {skills_dest}: {exc}"])

    roots = resolve_skills_roots(
        include_bundled=include_bundled,
        include_user=include_user,
        extra_roots=[Path(r) for r in extra_roots] if extra_roots else None,
    )
    if not roots:
        warnings.append("未找到 skills 源目录（templates/skills 或 ~/.xhaus/skills）")
        return SkillsLinkResult(linked, warnings, errors)

    seen_names: set[str] = set()
    for root in roots:
        for skill_md in discover_skill_files(root):
            skill_dir = skill_directory(skill_md).resolve()
            name = skill_dir.name
            if name in seen_names:
                continue
            seen_names.add(name)

            link_path = skills_dest / name
            if _same_target(link_path, skill_dir):
                linked.append(name)
                continue

            if link_path.exists() or link_path.is_symlink():
                if link_path.is_dir() and not link_path.is_symlink():
                    warnings.append(
                        f"skills/{name} 已是真实目录（非链接），保留原样未覆盖"
                    )
                    continue
                try:
                    link_path.unlink()
                except OSError as exc:
                    errors.append(f"无法替换 skills/{name}: {exc}")
                    continue

            try:
                # Relative symlink for portability within same volume; fall back to absolute.
                try:
                    rel = os.path.relpath(skill_dir, skills_dest)
                    if rel.startswith(".."):
                        link_path.symlink_to(skill_dir)
                    else:
                        link_path.symlink_to(rel)
                except (OSError, ValueError):
                    link_path.symlink_to(skill_dir)
            except OSError as exc:
                try:
                    _copy_skill_dir(skill_dir, link_path)
                    warnings.append(
                        f"已复制 skills/{name} 到 workspace（当前 Windows 权限不支持符号链接）"
                    )
                except OSError as copy_exc:
                    errors.append(
                        f"无法链接或复制 skills/{name} → {skill_dir}: "
                        f"link={exc}; copy={copy_exc}"
                    )
                    continue

            linked.append(name)

    return SkillsLinkResult(linked, warnings, errors)
