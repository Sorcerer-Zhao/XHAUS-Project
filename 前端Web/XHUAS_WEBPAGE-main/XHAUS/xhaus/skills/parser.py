"""Parse SKILL.md frontmatter and skill.meta.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_simple_yaml_block(block: str) -> dict[str, Any]:
    """Minimal YAML-like parser for frontmatter (no PyYAML dependency)."""
    data: dict[str, Any] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                data[key] = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
        elif value.lower() in ("true", "false"):
            data[key] = value.lower() == "true"
        else:
            data[key] = value
    return data


def split_skill_markdown(text: str) -> tuple[dict[str, Any], str]:
    """
    Split SKILL.md into frontmatter dict and markdown body.
    Returns ({}, full_text) when no frontmatter is present.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    frontmatter = _parse_simple_yaml_block(match.group(1))
    body = text[match.end() :]
    return frontmatter, body


def load_skill_meta_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Load optional skill.meta.json; returns (data, errors)."""
    errors: list[str] = []
    if not path.is_file():
        return {}, errors
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append(f"skill.meta.json 格式无效: {exc}")
        return {}, errors
    except OSError as exc:
        errors.append(f"无法读取 skill.meta.json: {exc}")
        return {}, errors

    if not isinstance(data, dict):
        errors.append("skill.meta.json 根节点必须是 JSON 对象")
        return {}, errors
    return data, errors


def merge_skill_metadata(
    *,
    directory_name: str,
    frontmatter: dict[str, Any],
    meta_json: dict[str, Any],
) -> tuple[str, str, str, bool, list[str], list[str]]:
    """
    Merge frontmatter + meta.json into unified fields.
    Returns (id, name, description, enabled, tags, warnings).
    """
    warnings: list[str] = []
    merged: dict[str, Any] = {**frontmatter, **meta_json}

    skill_id = str(merged.get("id") or merged.get("name") or directory_name).strip()
    if not skill_id:
        skill_id = directory_name

    name = str(merged.get("name") or skill_id).strip()
    description = str(merged.get("description") or "").strip()
    if not description:
        warnings.append("缺少 description，已使用空字符串")

    enabled = merged.get("enabled", True)
    if not isinstance(enabled, bool):
        warnings.append("enabled 字段无效，已默认为 true")
        enabled = True

    tags_raw = merged.get("tags", [])
    tags: list[str] = []
    if isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    elif isinstance(tags_raw, str) and tags_raw.strip():
        tags = [p.strip() for p in tags_raw.split(",") if p.strip()]
    elif tags_raw:
        warnings.append("tags 字段格式无效，已忽略")

    return skill_id, name, description, enabled, tags, warnings
