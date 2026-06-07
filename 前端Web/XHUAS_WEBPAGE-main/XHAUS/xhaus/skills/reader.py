"""Read a single skill entry from disk."""

from __future__ import annotations

from pathlib import Path

from xhaus.skills.models import SkillRecord
from xhaus.skills.parser import (
    load_skill_meta_json,
    merge_skill_metadata,
    split_skill_markdown,
)
from xhaus.skills.paths import SKILL_META_FILENAME
from xhaus.skills.scanner import skill_directory


def read_skill(skill_md_path: Path) -> SkillRecord:
    """
    Read one skill from its SKILL.md path.
    Never raises; returns SkillRecord with errors populated on failure.
    """
    skill_dir = skill_directory(skill_md_path)
    dir_name = skill_dir.name
    errors: list[str] = []
    warnings: list[str] = []

    if not skill_md_path.is_file():
        return SkillRecord(
            id=dir_name,
            name=dir_name,
            description="",
            path=skill_dir,
            skill_md_path=skill_md_path,
            valid=False,
            errors=[f"SKILL.md 不存在: {skill_md_path}"],
        )

    try:
        raw = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SkillRecord(
            id=dir_name,
            name=dir_name,
            description="",
            path=skill_dir,
            skill_md_path=skill_md_path,
            valid=False,
            errors=[f"无法读取 SKILL.md: {exc}"],
        )

    if not raw.strip():
        warnings.append("SKILL.md 为空")

    try:
        frontmatter, body = split_skill_markdown(raw)
    except Exception as exc:  # noqa: BLE001 — keep loader resilient
        return SkillRecord(
            id=dir_name,
            name=dir_name,
            description="",
            path=skill_dir,
            skill_md_path=skill_md_path,
            valid=False,
            errors=[f"SKILL.md 解析失败: {exc}"],
        )

    meta_path = skill_dir / SKILL_META_FILENAME
    meta_json, meta_errors = load_skill_meta_json(meta_path)
    errors.extend(meta_errors)

    skill_id, name, description, enabled, tags, merge_warnings = merge_skill_metadata(
        directory_name=dir_name,
        frontmatter=frontmatter,
        meta_json=meta_json,
    )
    warnings.extend(merge_warnings)

    merged_meta = {**frontmatter, **meta_json}

    return SkillRecord(
        id=skill_id,
        name=name,
        description=description,
        path=skill_dir,
        skill_md_path=skill_md_path,
        tags=tags,
        enabled=enabled,
        body=body.strip() or None,
        meta=merged_meta,
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
