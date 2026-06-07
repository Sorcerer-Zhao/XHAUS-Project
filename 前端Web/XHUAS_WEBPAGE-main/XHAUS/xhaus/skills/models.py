"""Skill data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillRecord:
    """
    Unified skill entry discovered under the skills root.

    Suitable for future Persona injection and Bridge forwarding.
    """

    id: str
    name: str
    description: str
    path: Path
    skill_md_path: Path
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    body: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for Bridge / logging (no full body by default)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "skill_md_path": str(self.skill_md_path),
            "tags": list(self.tags),
            "enabled": self.enabled,
            "valid": self.valid,
        }

    def to_injection_stub(self) -> dict[str, Any]:
        """
        Minimal payload reserved for future injection pipeline.
        Body omitted unless explicitly needed by Bridge.
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "enabled": self.enabled,
        }


@dataclass
class SkillRegistry:
    """All skills discovered from one or more roots."""

    roots: list[Path] = field(default_factory=list)
    skills: list[SkillRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def valid_skills(self) -> list[SkillRecord]:
        return [s for s in self.skills if s.valid]

    @property
    def enabled_skills(self) -> list[SkillRecord]:
        return [s for s in self.skills if s.valid and s.enabled]

    def get(self, skill_id: str) -> SkillRecord | None:
        for skill in self.skills:
            if skill.id == skill_id:
                return skill
        return None


@dataclass
class SkillLoadResult:
    """Outcome of a load operation; does not raise for per-skill failures."""

    registry: SkillRegistry
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"Skills 根目录: {', '.join(str(r) for r in self.registry.roots) or '(无)'}",
            f"条目数: {len(self.registry.skills)} "
            f"(有效 {len(self.registry.valid_skills)}, "
            f"启用 {len(self.registry.enabled_skills)})",
        ]
        for err in self.errors:
            lines.append(f"  [错误] {err}")
        for warn in self.warnings:
            lines.append(f"  [警告] {warn}")
        for skill in self.registry.skills:
            if skill.errors:
                for e in skill.errors:
                    lines.append(f"  [skill:{skill.id}] {e}")
        return "\n".join(lines)


@dataclass
class SkillInjectionBundle:
    """Reserved bundle for Persona / Bridge layers (no injection this round)."""

    skills: list[SkillRecord] = field(default_factory=list)

    def to_persona_context(self) -> str:
        """Placeholder — future: format skill summaries for persona mount."""
        if not self.skills:
            return ""
        lines = ["## Available Skills"]
        for s in self.skills:
            lines.append(f"- **{s.name}**: {s.description}")
        return "\n".join(lines)

    def to_bridge_payload(self) -> dict[str, Any]:
        """Placeholder — future: OpenClaw Bridge message shape."""
        return {
            "type": "xhaus.skills.bundle",
            "version": 1,
            "skills": [s.to_injection_stub() for s in self.skills],
        }
