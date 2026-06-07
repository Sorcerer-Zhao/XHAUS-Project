"""Profile data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator


class ProfileDocumentKind(str, Enum):
    """The four persona documents that compose a Profile."""

    IDENTITY = "IDENTITY"
    SOUL = "SOUL"
    AGENTS = "AGENTS"
    USER = "USER"

    @property
    def filename(self) -> str:
        return f"{self.value}.md"


# Stable load order for reporting and iteration.
PROFILE_DOCUMENT_ORDER: tuple[ProfileDocumentKind, ...] = tuple(ProfileDocumentKind)


class ProfileSource(str, Enum):
    """Where a Profile was loaded from."""

    PRESET = "preset"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ProfileDocument:
    """A single document section within a Profile."""

    kind: ProfileDocumentKind
    content: str | None
    path: Path | None
    exists: bool
    error: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self.exists and self.content is not None


@dataclass
class Profile:
    """
    Unified Profile: four documents (IDENTITY, SOUL, AGENTS, USER)
  representing persona and runtime context for XHAUS.
    """

    name: str
    source: ProfileSource
    base_path: Path
    documents: dict[ProfileDocumentKind, ProfileDocument] = field(default_factory=dict)

    def get(self, kind: ProfileDocumentKind) -> ProfileDocument | None:
        return self.documents.get(kind)

    def iter_documents(self) -> Iterator[ProfileDocument]:
        for kind in PROFILE_DOCUMENT_ORDER:
            doc = self.documents.get(kind)
            if doc is not None:
                yield doc

    @property
    def identity(self) -> ProfileDocument | None:
        return self.get(ProfileDocumentKind.IDENTITY)

    @property
    def soul(self) -> ProfileDocument | None:
        return self.get(ProfileDocumentKind.SOUL)

    @property
    def agents(self) -> ProfileDocument | None:
        return self.get(ProfileDocumentKind.AGENTS)

    @property
    def user(self) -> ProfileDocument | None:
        return self.get(ProfileDocumentKind.USER)

    @property
    def missing_kinds(self) -> list[ProfileDocumentKind]:
        return [kind for kind in PROFILE_DOCUMENT_ORDER if not self._doc_exists(kind)]

    @property
    def is_complete(self) -> bool:
        return len(self.missing_kinds) == 0

    @property
    def errors(self) -> list[str]:
        return [doc.error for doc in self.iter_documents() if doc.error]

    def _doc_exists(self, kind: ProfileDocumentKind) -> bool:
        doc = self.documents.get(kind)
        return doc is not None and doc.is_loaded


@dataclass
class ProfileLoadResult:
    """Outcome of loading a Profile; never raises for missing documents."""

    profile: Profile | None
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        """Human-readable summary for CLI or logging."""
        lines: list[str] = []
        if self.profile is None:
            lines.append("Profile 加载失败")
        else:
            p = self.profile
            lines.append(f"Profile: {p.name} ({p.source.value})")
            lines.append(f"路径: {p.base_path}")
            lines.append(f"完整: {'是' if self.ok else '否'}")
        for err in self.errors:
            lines.append(f"  [错误] {err}")
        for warn in self.warnings:
            lines.append(f"  [警告] {warn}")
        return "\n".join(lines)
