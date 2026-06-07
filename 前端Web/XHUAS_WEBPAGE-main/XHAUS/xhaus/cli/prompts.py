"""Reusable CLI prompt helpers."""

from __future__ import annotations

import getpass
from collections.abc import Callable

SUBSECTION_INDENT = "\t"


def print_step(step: int, total: int, title: str) -> None:
    print()
    print("─" * 50)
    print(f"  步骤 {step}/{total} · {title}")
    print("─" * 50)
    print()


def print_subsection(title: str, *, indent: int = 1) -> None:
    """Indented sub-block (e.g. OpenClaw Agent under custom profile)."""
    prefix = SUBSECTION_INDENT * indent
    print()
    print(f"{prefix}▸ {title}")
    print()


def iprint(message: str, *, indent: int = 1) -> None:
    """Print with tab indentation."""
    prefix = SUBSECTION_INDENT * indent
    for line in message.splitlines():
        print(f"{prefix}{line}" if line else "")


def ask(
    label: str,
    *,
    validator: Callable[[str], tuple[bool, str]] | None = None,
    default: str | None = None,
    hint: str | None = None,
    indent: int = 0,
) -> str:
    """
    Prompt until validation passes.
    validator returns (ok, value_or_error_message).
    """
    prefix = SUBSECTION_INDENT * indent
    while True:
        suffix = f" [{default}]" if default else ""
        if hint:
            print(f"{prefix}  提示: {hint}")
        raw = input(f"{prefix}{label}{suffix}: ").strip()
        if not raw and default is not None:
            raw = default

        if validator is None:
            return raw

        ok, result = validator(raw)
        if ok:
            return result
        iprint(f"⚠ {result}", indent=indent)
        print()


def ask_secret(label: str, *, indent: int = 0) -> str:
    """Masked input for API keys."""
    prefix = SUBSECTION_INDENT * indent
    while True:
        value = getpass.getpass(f"{prefix}{label}: ").strip()
        if value:
            return value
        iprint("⚠ 不能为空", indent=indent)


def ask_confirm(label: str, *, default_yes: bool = True, indent: int = 0) -> bool:
    from xhaus.cli.validators import validate_confirm

    prefix = SUBSECTION_INDENT * indent
    default_hint = "Y/n" if default_yes else "y/N"
    while True:
        raw = input(f"{prefix}{label} ({default_hint}): ").strip()
        if not raw:
            return default_yes
        ok, accepted = validate_confirm(raw)
        if ok:
            return accepted
        iprint("⚠ 请输入 y/是 或 n/否。", indent=indent)
