"""Scan skills roots for SKILL.md entries."""

from __future__ import annotations

from pathlib import Path

from xhaus.skills.paths import IGNORE_DIR_NAMES, SKILL_MD_FILENAME


def _should_skip_relative(rel: Path) -> bool:
    """Skip hidden or ignored directories relative to the skills root only."""
    for part in rel.parts[:-1]:
        if part in IGNORE_DIR_NAMES:
            return True
        if part.startswith("."):
            return True
    return False


def discover_skill_files(root: Path) -> list[Path]:
    """
    Recursively find SKILL.md files under root.
    Each file's parent directory is treated as one skill entry.
    """
    if not root.is_dir():
        return []

    root = root.resolve()
    found: list[Path] = []
    for skill_md in root.rglob(SKILL_MD_FILENAME):
        if not skill_md.is_file():
            continue
        try:
            rel = skill_md.resolve().relative_to(root)
        except ValueError:
            continue
        if _should_skip_relative(rel):
            continue
        found.append(skill_md.resolve())
    return sorted(found, key=lambda p: str(p).lower())


def skill_directory(skill_md_path: Path) -> Path:
    """Directory that owns this skill (parent of SKILL.md)."""
    return skill_md_path.parent
