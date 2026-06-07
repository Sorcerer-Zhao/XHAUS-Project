"""Patch ~/.openclaw/openclaw.json for shared XHAUS skills symlinks."""

from __future__ import annotations

import json
import os
from pathlib import Path


def resolve_openclaw_config_path() -> Path:
    raw = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".openclaw" / "openclaw.json"


def ensure_allow_symlink_targets(
    roots: list[Path],
    *,
    config_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    """
    Merge absolute paths into skills.load.allowSymlinkTargets.

    Returns (added_paths, errors).
    """
    cfg_path = (config_path or resolve_openclaw_config_path()).expanduser()
    if not cfg_path.is_file():
        return [], [f"OpenClaw 配置文件不存在: {cfg_path}"]

    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"无法读取 {cfg_path}: {exc}"]

    if not isinstance(data, dict):
        return [], [f"配置格式无效: {cfg_path}"]

    skills = data.setdefault("skills", {})
    if not isinstance(skills, dict):
        skills = {}
        data["skills"] = skills
    load = skills.setdefault("load", {})
    if not isinstance(load, dict):
        load = {}
        skills["load"] = load

    existing_raw = load.get("allowSymlinkTargets")
    existing: list[str] = []
    if isinstance(existing_raw, list):
        existing = [str(x) for x in existing_raw if isinstance(x, str) and x.strip()]

    existing_set = {Path(p).expanduser().resolve() for p in existing}
    added: list[str] = []
    for root in roots:
        resolved = root.expanduser().resolve()
        if resolved in existing_set:
            continue
        existing.append(str(resolved))
        existing_set.add(resolved)
        added.append(str(resolved))

    if not added:
        return [], []

    load["allowSymlinkTargets"] = existing
    try:
        cfg_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return [], [f"无法写入 {cfg_path}: {exc}"]

    return added, []
