"""XHAUS application entry and lifecycle."""

from xhaus.cli.wizard import run_wizard


def run() -> None:
    """Start XHAUS: CLI wizard → activation pipeline (MVP)."""
    run_wizard()
