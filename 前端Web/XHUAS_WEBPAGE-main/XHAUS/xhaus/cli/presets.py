"""Scan presets directory and build role menu options."""

from __future__ import annotations

import json
from pathlib import Path

from xhaus.cli.menu import MenuChoice
from xhaus.cli.validators import ROLE_CUSTOM, ROLE_CUSTOM_PROFILE_PREFIX
from xhaus.config.models import PROFILE_DOCUMENT_ORDER
from xhaus.config.paths import (
    custom_profiles_root,
    list_custom_profile_names,
    list_preset_names,
    presets_root,
)

# Built-in display names for bundled presets (overridable via preset.meta.json).
KNOWN_PRESET_LABELS: dict[str, str] = {
    "default_butler": "默认管家",
    "elegant_maid": "优雅女仆",
}

# Prefer this order when both exist; additional presets sort alphabetically after.
PRESET_ORDER_PRIORITY: tuple[str, ...] = ("default_butler", "elegant_maid")


def _has_profile_documents(preset_dir: Path) -> bool:
    """A directory counts as a role preset if it has at least one profile document."""
    return any((preset_dir / kind.filename).is_file() for kind in PROFILE_DOCUMENT_ORDER)


def _read_meta_label(preset_dir: Path) -> str | None:
    meta_path = preset_dir / "preset.meta.json"
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    label = data.get("label")
    return label if isinstance(label, str) and label.strip() else None


def preset_display_label(name: str, preset_dir: Path) -> str:
    """Resolve human-readable label for a preset folder."""
    from_meta = _read_meta_label(preset_dir)
    if from_meta:
        return from_meta.strip()
    if name in KNOWN_PRESET_LABELS:
        return KNOWN_PRESET_LABELS[name]
    return name.replace("_", " ")


def _sort_preset_names(names: list[str]) -> list[str]:
    priority = {n: i for i, n in enumerate(PRESET_ORDER_PRIORITY)}

    def sort_key(n: str) -> tuple[int, str]:
        if n in priority:
            return (0, str(priority[n]))
        return (1, n)

    return sorted(names, key=sort_key)


def scan_preset_choices() -> list[MenuChoice]:
    """
    Scan presets/ on each run; include every valid preset directory plus custom.
    New folders with profile documents appear automatically in the menu.
    """
    choices: list[MenuChoice] = []
    root = presets_root()

    valid_names: list[str] = []
    for name in list_preset_names():
        preset_dir = root / name
        if preset_dir.is_dir() and _has_profile_documents(preset_dir):
            valid_names.append(name)

    for name in _sort_preset_names(valid_names):
        preset_dir = root / name
        choices.append(
            MenuChoice(
                label=preset_display_label(name, preset_dir),
                value=name,
            )
        )

    custom_root = custom_profiles_root()
    for name in list_custom_profile_names():
        profile_dir = custom_root / name
        if not _has_profile_documents(profile_dir):
            continue
        label = _read_meta_label(profile_dir) or name
        if label == name:
            label = f"{name}（我的管家）"
        choices.append(
            MenuChoice(
                label=label,
                value=f"{ROLE_CUSTOM_PROFILE_PREFIX}{name}",
            )
        )

    choices.append(MenuChoice(label="自定义角色", value=ROLE_CUSTOM))
    return choices


def is_saved_custom_profile(role_key: str) -> bool:
    return role_key.startswith(ROLE_CUSTOM_PROFILE_PREFIX)


def saved_custom_profile_name(role_key: str) -> str:
    return role_key[len(ROLE_CUSTOM_PROFILE_PREFIX) :]
