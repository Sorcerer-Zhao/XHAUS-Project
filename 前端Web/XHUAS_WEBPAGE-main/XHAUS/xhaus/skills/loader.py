"""Load skills from configured roots into a SkillRegistry."""

from __future__ import annotations

from pathlib import Path

from xhaus.skills.models import SkillLoadResult, SkillRecord, SkillRegistry
from xhaus.skills.paths import (
    default_skills_root,
    is_default_user_skills_root,
    resolve_skills_roots,
)
from xhaus.skills.reader import read_skill
from xhaus.skills.scanner import discover_skill_files


def load_skills_from_root(
    root: Path,
    *,
    seen_ids: set[str] | None = None,
) -> tuple[list[SkillRecord], list[str], list[str]]:
    """
    Scan and read all skills under one root.
    Returns (skills, errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []
    skills: list[SkillRecord] = []
    seen = seen_ids if seen_ids is not None else set()

    if not root.exists():
        if is_default_user_skills_root(root):
            return skills, errors, warnings
        warnings.append(f"skills 目录不存在，已跳过: {root}")
        return skills, errors, warnings

    if not root.is_dir():
        errors.append(f"skills 路径不是目录: {root}")
        return skills, errors, warnings

    skill_files = discover_skill_files(root)
    if not skill_files and root.exists() and not is_default_user_skills_root(root):
        warnings.append(f"目录下未发现 SKILL.md: {root}")

    for skill_md in skill_files:
        record = read_skill(skill_md)
        if record.id in seen:
            warnings.append(
                f"重复的 skill id {record.id!r}，已跳过: {record.path}"
            )
            continue
        seen.add(record.id)
        skills.append(record)
        if record.warnings:
            warnings.extend(f"[{record.id}] {w}" for w in record.warnings)

    return skills, errors, warnings


def load_skills(
    *,
    roots: list[Path | str] | None = None,
    include_bundled: bool = True,
    include_user: bool = True,
) -> SkillLoadResult:
    """
    Scan all configured roots and build a unified SkillRegistry.
    Never raises for missing roots or broken individual skills.
    """
    resolved_roots = (
        [Path(r).expanduser().resolve() for r in roots]
        if roots
        else resolve_skills_roots(
            include_bundled=include_bundled,
            include_user=include_user,
        )
    )

    registry = SkillRegistry(roots=resolved_roots)
    seen_ids: set[str] = set()
    global_errors: list[str] = []
    global_warnings: list[str] = []

    if not resolved_roots:
        global_warnings.append(
            "未配置任何 skills 根目录；可设置 XHAUS_SKILLS_DIR 或使用 bundled/user 默认路径"
        )

    for root in resolved_roots:
        batch, errs, warns = load_skills_from_root(root, seen_ids=seen_ids)
        registry.skills.extend(batch)
        global_errors.extend(errs)
        global_warnings.extend(warns)

    for skill in registry.skills:
        if skill.errors:
            global_errors.extend(f"[{skill.id}] {e}" for e in skill.errors)

    registry.errors = global_errors
    registry.warnings = global_warnings

    ok = not global_errors
    return SkillLoadResult(registry=registry, ok=ok, errors=global_errors, warnings=global_warnings)


def load_skills_default() -> SkillLoadResult:
    """Load from default roots (bundled + ~/.xhaus/skills)."""
    return load_skills()
