"""Skill Manager — high-level API and injection hooks (stubs)."""

from __future__ import annotations

from pathlib import Path

from xhaus.skills.loader import load_skills, load_skills_from_root
from xhaus.skills.models import (
    SkillInjectionBundle,
    SkillLoadResult,
    SkillRecord,
    SkillRegistry,
)
from xhaus.skills.paths import default_skills_root


class SkillManager:
    """
    Unified entry for skill scan / read / load.

    Does not execute skills or perform Bridge injection in this round.
    """

    def __init__(
        self,
        *,
        roots: list[Path | str] | None = None,
        include_bundled: bool = True,
        include_user: bool = True,
    ) -> None:
        self._roots = roots
        self._include_bundled = include_bundled
        self._include_user = include_user
        self._result: SkillLoadResult | None = None

    @property
    def registry(self) -> SkillRegistry | None:
        if self._result is None:
            return None
        return self._result.registry

    def load(self, *, refresh: bool = False) -> SkillLoadResult:
        """Scan and load skills into memory."""
        if self._result is not None and not refresh:
            return self._result

        self._result = load_skills(
            roots=self._roots,
            include_bundled=self._include_bundled,
            include_user=self._include_user,
        )
        return self._result

    def enabled_skills(self) -> list[SkillRecord]:
        result = self.load()
        return result.registry.enabled_skills

    def get(self, skill_id: str) -> SkillRecord | None:
        result = self.load()
        return result.registry.get(skill_id)

    def build_injection_bundle(self) -> SkillInjectionBundle:
        """
        Reserved for Persona / Bridge injection.
        Returns enabled, valid skills only.
        """
        result = self.load()
        return SkillInjectionBundle(skills=result.registry.enabled_skills)

    def prepare_bridge_payload(self) -> dict:
        """Reserved: payload shape for OpenClaw Bridge (not sent this round)."""
        return self.build_injection_bundle().to_bridge_payload()

    def prepare_persona_context(self) -> str:
        """Reserved: text block for persona mount (not applied this round)."""
        return self.build_injection_bundle().to_persona_context()


def create_default_manager() -> SkillManager:
    """Manager using default roots."""
    return SkillManager()
