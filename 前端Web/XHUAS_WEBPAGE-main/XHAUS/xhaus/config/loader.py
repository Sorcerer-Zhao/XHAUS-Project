"""Profile loading: presets and custom directories."""

from __future__ import annotations

from pathlib import Path

from xhaus.config.errors import ProfileConfigError, ProfileDirectoryError, ProfileNotFoundError
from xhaus.config.models import (
    PROFILE_DOCUMENT_ORDER,
    Profile,
    ProfileDocument,
    ProfileDocumentKind,
    ProfileLoadResult,
    ProfileSource,
)
from xhaus.config.paths import list_preset_names, resolve_custom_path, resolve_preset_path
from xhaus.config.validation import collect_warnings, validate_document_file, validate_profile


def _load_documents(base_path: Path) -> dict[ProfileDocumentKind, ProfileDocument]:
    return {
        kind: validate_document_file(kind, base_path)
        for kind in PROFILE_DOCUMENT_ORDER
    }


def _build_result(
    *,
    name: str,
    source: ProfileSource,
    base_path: Path,
    fatal_errors: list[str] | None = None,
) -> ProfileLoadResult:
    fatal = list(fatal_errors or [])
    if fatal:
        return ProfileLoadResult(profile=None, ok=False, errors=fatal)

    documents = _load_documents(base_path)
    profile = Profile(
        name=name,
        source=source,
        base_path=base_path,
        documents=documents,
    )
    errors = validate_profile(profile)
    warnings = collect_warnings(profile)
    ok = len(errors) == 0
    return ProfileLoadResult(
        profile=profile,
        ok=ok,
        errors=errors,
        warnings=warnings,
    )


def load_preset(name: str) -> ProfileLoadResult:
    """
    Load a bundled preset profile by name (e.g. default_butler, elegant_maid).
    Missing documents are reported in result.errors; does not raise.
    """
    try:
        base_path = resolve_preset_path(name)
    except ProfileNotFoundError as exc:
        return ProfileLoadResult(profile=None, ok=False, errors=[str(exc)])
    except ProfileConfigError as exc:
        return ProfileLoadResult(profile=None, ok=False, errors=[str(exc)])

    return _build_result(name=name, source=ProfileSource.PRESET, base_path=base_path)


def load_from_directory(path: str | Path, *, name: str | None = None) -> ProfileLoadResult:
    """
    Load a custom profile from a directory containing IDENTITY.md, SOUL.md,
    AGENTS.md, and USER.md. Missing documents are reported; does not raise.
    """
    try:
        base_path = resolve_custom_path(path)
    except ProfileDirectoryError as exc:
        return ProfileLoadResult(profile=None, ok=False, errors=[str(exc)])

    profile_name = name or base_path.name
    return _build_result(
        name=profile_name,
        source=ProfileSource.CUSTOM,
        base_path=base_path,
    )


def load_profile(
    *,
    preset: str | None = None,
    path: str | Path | None = None,
) -> ProfileLoadResult:
    """
    Load a profile by preset name or custom path. Exactly one of preset/path required.
    """
    if preset and path:
        return ProfileLoadResult(
            profile=None,
            ok=False,
            errors=["请只指定 preset 或 path 之一，不能同时指定"],
        )
    if preset:
        return load_preset(preset)
    if path:
        return load_from_directory(path)
    return ProfileLoadResult(
        profile=None,
        ok=False,
        errors=["请指定 preset 或 path"],
    )


def available_presets() -> list[str]:
    """List bundled preset profile names."""
    return list_preset_names()
