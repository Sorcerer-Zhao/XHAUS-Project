"""Skills directory resolution."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_SKILLS_DIR = _PACKAGE_ROOT / "templates" / "skills"
SKILLS_ROOT_ENV = "XHAUS_SKILLS_DIR"

# Marker files
SKILL_MD_FILENAME = "SKILL.md"
SKILL_META_FILENAME = "skill.meta.json"

# Directories skipped during recursive scan
IGNORE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".cursor",
        "dist",
        "build",
    }
)


def default_skills_root() -> Path:
    """User skills root: $XHAUS_SKILLS_DIR or ~/.xhaus/skills."""
    env = os.environ.get(SKILLS_ROOT_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".xhaus" / "skills"


def bundled_skills_root() -> Path:
    """Optional bundled skills shipped with XHAUS."""
    return BUNDLED_SKILLS_DIR


def is_default_user_skills_root(path: Path) -> bool:
    """True when path is the optional ~/.xhaus/skills default (not env override)."""
    if os.environ.get(SKILLS_ROOT_ENV, "").strip():
        return False
    return path.resolve() == (Path.home() / ".xhaus" / "skills").resolve()


def resolve_skills_roots(
    *,
    extra_roots: list[Path | str] | None = None,
    include_bundled: bool = True,
    include_user: bool = True,
) -> list[Path]:
    """
    Return ordered list of skills roots to scan.
    Later roots do not override earlier skill ids (first wins).

  Bundled: xhaus/templates/skills/ (project-shipped or local copies)
  User:    ~/.xhaus/skills/ or $XHAUS_SKILLS_DIR (optional extra install location)
    """
    roots: list[Path] = []
    if include_bundled:
        bundled = bundled_skills_root()
        if bundled.is_dir():
            roots.append(bundled.resolve())
    if include_user:
        user_root = default_skills_root().resolve()
        # Default ~/.xhaus/skills is optional — skip when absent (no warning).
        if user_root.exists() or os.environ.get(SKILLS_ROOT_ENV, "").strip():
            roots.append(user_root)
    if extra_roots:
        for item in extra_roots:
            roots.append(Path(item).expanduser().resolve())
    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique
