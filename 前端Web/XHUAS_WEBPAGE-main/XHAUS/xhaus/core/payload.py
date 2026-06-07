"""Unified mount payload — Profile + Skills for OpenClaw."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from xhaus.config.models import PROFILE_DOCUMENT_ORDER, Profile, ProfileDocumentKind
from xhaus.skills.models import SkillRecord, SkillRegistry

PAYLOAD_VERSION = 1
PAYLOAD_TYPE = "xhaus.mount"


@dataclass
class MountPayload:
    """Wire format sent to OpenClaw (xhaus.mount) or applied via fallback APIs."""

    version: int
    profile: dict[str, Any]
    skills: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": PAYLOAD_TYPE,
            "version": self.version,
            "profile": self.profile,
            "skills": self.skills,
            "meta": self.meta,
        }


def profile_to_payload_dict(profile: Profile) -> dict[str, Any]:
    """Extract IDENTITY / SOUL / AGENTS / USER document bodies."""
    documents: dict[str, str | None] = {}
    paths: dict[str, str | None] = {}
    for kind in PROFILE_DOCUMENT_ORDER:
        key = kind.value
        doc = profile.get(kind)
        documents[key] = doc.content if doc and doc.is_loaded else None
        paths[key] = str(doc.path) if doc and doc.path else None
    return {
        "name": profile.name,
        "source": profile.source.value,
        "base_path": str(profile.base_path),
        "documents": documents,
        "paths": paths,
        "filenames": {kind.value: kind.filename for kind in PROFILE_DOCUMENT_ORDER},
    }


def skills_to_payload_list(skills: list[SkillRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "enabled": s.enabled,
            "path": str(s.path),
            "valid": s.valid,
        }
        for s in skills
    ]


def build_mount_payload(
    profile: Profile,
    registry: SkillRegistry,
    *,
    role_label: str | None = None,
    websocket_url: str | None = None,
) -> MountPayload:
    """Pack profile + enabled skills into a unified mount payload."""
    enabled = registry.enabled_skills
    return MountPayload(
        version=PAYLOAD_VERSION,
        profile=profile_to_payload_dict(profile),
        skills=skills_to_payload_list(enabled),
        meta={
            "role_label": role_label,
            "websocket_url": websocket_url,
            "skill_count": len(enabled),
            "profile_complete": profile.is_complete,
        },
    )


def document_filename(kind: ProfileDocumentKind) -> str:
    return kind.filename
