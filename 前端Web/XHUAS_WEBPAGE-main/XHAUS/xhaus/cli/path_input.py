"""Normalize paths pasted or drag-dropped into the terminal."""

from __future__ import annotations

from pathlib import Path


def normalize_path_input(value: str) -> str:
    """
    Clean terminal path input.

    macOS drag-and-drop often inserts a leading ``'`` without a closing quote,
    e.g. ``'/Users/me/skills/test1`` — which would otherwise be treated as a
    relative path under the current working directory.
    """
    text = value.strip()
    if not text:
        return text

    # Fully wrapped in matching quotes
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    else:
        # Lone opening/closing quote from incomplete drag-and-drop
        text = text.strip("'\"")

    # Collapse accidental backslash-escaped spaces from some terminals
    return text.replace("\\ ", " ").strip()


def parse_path_input(value: str) -> Path:
    """Parse user path input into a resolved absolute Path."""
    cleaned = normalize_path_input(value)
    if not cleaned:
        return Path(cleaned)
    path = Path(cleaned).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()
