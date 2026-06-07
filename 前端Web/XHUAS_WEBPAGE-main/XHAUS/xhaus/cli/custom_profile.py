"""Custom profile directory setup and document editing."""

from __future__ import annotations

import shutil
from pathlib import Path

from xhaus.config.models import PROFILE_DOCUMENT_ORDER
from xhaus.config.paths import default_custom_profiles_root, resolve_preset_path
from xhaus.utils.editor import open_in_editor

DEFAULT_TEMPLATE_PRESET = "default_butler"


def custom_profile_dir(name: str) -> Path:
    return default_custom_profiles_root() / name


def ensure_custom_profile(name: str) -> tuple[Path, bool]:
    """
    Ensure custom profile directory exists with four template files.
    Returns (path, created_new).
    """
    dest = custom_profile_dir(name)
    if dest.is_dir() and any((dest / k.filename).is_file() for k in PROFILE_DOCUMENT_ORDER):
        return dest, False

    dest.mkdir(parents=True, exist_ok=True)
    source = resolve_preset_path(DEFAULT_TEMPLATE_PRESET)
    for kind in PROFILE_DOCUMENT_ORDER:
        src_file = source / kind.filename
        dst_file = dest / kind.filename
        if not dst_file.is_file():
            if src_file.is_file():
                shutil.copy2(src_file, dst_file)
            else:
                dst_file.write_text(f"# {kind.value}\n\n", encoding="utf-8")
    return dest, True


def edit_profile_documents(profile_dir: Path) -> list[str]:
    """
    Open each Profile document in the editor sequentially.
    Returns list of error messages (empty if all ok).
    """
    errors: list[str] = []
    for kind in PROFILE_DOCUMENT_ORDER:
        path = profile_dir / kind.filename
        print()
        print(f"  → 即将编辑: {kind.value} ({path})")
        input("  按 Enter 打开编辑器… ")
        ok, msg = open_in_editor(path)
        if not ok:
            errors.append(f"{kind.value}: {msg}")
            retry = input("  是否跳过此文件并继续？(y/N): ").strip().lower()
            if retry not in ("y", "yes", "是"):
                errors.append(f"用户中止编辑 {kind.value}")
                break
        else:
            print(f"  ✓ 已编辑: {msg}")
    return errors
