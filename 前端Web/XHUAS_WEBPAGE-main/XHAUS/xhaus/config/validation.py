"""Profile validation helpers."""

from __future__ import annotations

from pathlib import Path

from xhaus.config.models import (
    PROFILE_DOCUMENT_ORDER,
    Profile,
    ProfileDocument,
    ProfileDocumentKind,
)


def missing_document_message(kind: ProfileDocumentKind, base_path: Path) -> str:
    expected = base_path / kind.filename
    return f"缺少文档 {kind.value}: 期望文件 {expected}"


def validate_document_file(
    kind: ProfileDocumentKind,
    base_path: Path,
) -> ProfileDocument:
    """
    Read one document if present; return ProfileDocument with error set when missing.
    Does not raise.
    """
    path = base_path / kind.filename
    if not path.is_file():
        return ProfileDocument(
            kind=kind,
            content=None,
            path=path,
            exists=False,
            error=missing_document_message(kind, base_path),
        )

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ProfileDocument(
            kind=kind,
            content=None,
            path=path,
            exists=True,
            error=f"无法读取 {kind.value} ({path}): {exc}",
        )

    return ProfileDocument(
        kind=kind,
        content=content,
        path=path,
        exists=True,
        error=None,
    )


def validate_profile(profile: Profile) -> list[str]:
    """Collect all document-level errors for a Profile."""
    return list(profile.errors)


def collect_warnings(profile: Profile) -> list[str]:
    """Non-fatal issues such as empty document bodies."""
    warnings: list[str] = []
    for doc in profile.iter_documents():
        if doc.is_loaded and doc.content is not None and not doc.content.strip():
            warnings.append(f"{doc.kind.value} 内容为空: {doc.path}")
    return warnings


def validate_directory_structure(base_path: Path) -> tuple[list[str], list[str]]:
    """
    Check that all four documents exist under base_path.
    Returns (errors, warnings) without raising.
    """
    errors: list[str] = []
    warnings: list[str] = []
    for kind in PROFILE_DOCUMENT_ORDER:
        path = base_path / kind.filename
        if not path.is_file():
            errors.append(missing_document_message(kind, base_path))
        elif not path.read_text(encoding="utf-8").strip():
            warnings.append(f"{kind.value} 文件为空: {path}")
    return errors, warnings
