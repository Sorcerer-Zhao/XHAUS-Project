"""Terminal line input — Unicode/IME-safe editing for console chat."""

from __future__ import annotations

_session = None


def read_line(prompt: str) -> str:
    """
    Read one user line with proper backspace/delete under CJK IME.

    Plain ``input()`` can desync displayed text from the submitted buffer when
    the user edits with backspace while composing Chinese/Japanese/Korean text.
    ``prompt_toolkit`` keeps the buffer consistent with what is shown on screen.
    """
    global _session
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
    except ImportError:
        return input(prompt)

    if _session is None:
        _session = PromptSession(
            history=InMemoryHistory(),
            enable_open_in_editor=False,
        )
    return _session.prompt(prompt)
