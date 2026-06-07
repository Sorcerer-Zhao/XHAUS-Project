"""Profile configuration errors."""

from __future__ import annotations


class ProfileConfigError(Exception):
    """Base error for profile configuration issues."""


class ProfileNotFoundError(ProfileConfigError):
    """Raised when a preset or profile directory cannot be resolved."""

    def __init__(self, name: str, *, kind: str = "preset") -> None:
        self.name = name
        self.kind = kind
        super().__init__(f"{kind} profile not found: {name!r}")


class ProfileDirectoryError(ProfileConfigError):
    """Raised when a custom profile path is invalid."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"invalid profile directory {path!r}: {reason}")
