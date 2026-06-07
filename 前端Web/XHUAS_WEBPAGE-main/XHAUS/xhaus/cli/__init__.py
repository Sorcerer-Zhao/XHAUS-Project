"""CLI layer — interactive wizards and command-line entry points."""

from xhaus.cli.menu import MenuChoice, select_menu
from xhaus.cli.presets import scan_preset_choices
from xhaus.cli.wizard import WizardResult, run_wizard

__all__ = [
    "MenuChoice",
    "WizardResult",
    "run_wizard",
    "scan_preset_choices",
    "select_menu",
]
