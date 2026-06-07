"""Profile path resolution for presets and custom directories."""

from __future__ import annotations

import os
from pathlib import Path

from xhaus.config.errors import ProfileDirectoryError, ProfileNotFoundError

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = _PACKAGE_ROOT / "templates" / "profiles" / "presets"
CUSTOM_PROFILES_ENV = "XHAUS_PROFILES_DIR"


def presets_root() -> Path:
    return PRESETS_DIR


def list_preset_names() -> list[str]:
    """Return sorted preset profile names bundled with XHAUS."""
    root = presets_root()
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def resolve_preset_path(name: str) -> Path:
    """Resolve a preset profile directory by name."""
    path = presets_root() / name
    if not path.is_dir():
        available = ", ".join(list_preset_names()) or "(none)"
        raise ProfileNotFoundError(
            name,
            kind=f"preset (available: {available})",
        )
    return path


def resolve_custom_path(path: str | Path) -> Path:
    """Resolve and validate a user-provided custom profile directory."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise ProfileDirectoryError(str(path), "path does not exist")
    if not resolved.is_dir():
        raise ProfileDirectoryError(str(path), "path is not a directory")
    return resolved


def default_custom_profiles_root() -> Path:
    """Default location for user-defined profiles: ~/.xhaus/profiles."""
    env = os.environ.get(CUSTOM_PROFILES_ENV, "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".xhaus" / "profiles"


def custom_profiles_root() -> Path:
    """Alias for the active custom profiles directory."""
    return default_custom_profiles_root()


def list_custom_profile_names() -> list[str]:
    """Return sorted names of saved custom profiles under ~/.xhaus/profiles."""
    root = custom_profiles_root()
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
