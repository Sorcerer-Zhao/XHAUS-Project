"""Skills layer — discovery, loading, and injection preparation."""

from xhaus.skills.loader import load_skills, load_skills_default, load_skills_from_root
from xhaus.skills.manager import SkillManager, create_default_manager
from xhaus.skills.models import (
    SkillInjectionBundle,
    SkillLoadResult,
    SkillRecord,
    SkillRegistry,
)
from xhaus.skills.paths import (
    SKILL_MD_FILENAME,
    SKILL_META_FILENAME,
    bundled_skills_root,
    default_skills_root,
    resolve_skills_roots,
)
from xhaus.skills.scanner import discover_skill_files

__all__ = [
    "SKILL_MD_FILENAME",
    "SKILL_META_FILENAME",
    "SkillInjectionBundle",
    "SkillLoadResult",
    "SkillManager",
    "SkillRecord",
    "SkillRegistry",
    "bundled_skills_root",
    "create_default_manager",
    "default_skills_root",
    "discover_skill_files",
    "load_skills",
    "load_skills_default",
    "load_skills_from_root",
    "resolve_skills_roots",
]
