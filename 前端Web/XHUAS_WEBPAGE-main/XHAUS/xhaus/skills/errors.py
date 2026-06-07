"""Skill loading errors (collected; rarely raised to callers)."""

from __future__ import annotations


class SkillError(Exception):
    """Base error for skill subsystem."""


class SkillParseError(SkillError):
    """Skill metadata or SKILL.md could not be parsed."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"skill parse failed for {path!r}: {reason}")
