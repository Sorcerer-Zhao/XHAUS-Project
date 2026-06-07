"""Bridge layer errors."""

from __future__ import annotations

from xhaus.core.bridge.models import BridgeState


class BridgeError(Exception):
    """Base error for the message bridge."""

    def __init__(self, message: str, *, state: BridgeState | None = None) -> None:
        self.state = state
        if state is not None:
            message = f"{message} (state={state.value})"
        super().__init__(message)


class BridgeStateError(BridgeError):
    """Operation not allowed in the current bridge state."""


class BridgeNotMountedError(BridgeError):
    """Runtime connector is not mounted."""


class BridgeAlreadyClosedError(BridgeError):
    """Bridge has already been closed."""


class BridgeConnectionError(BridgeError):
    """Failed to connect or communicate with the runtime."""


class BridgeMessageError(BridgeError):
    """Message send or receive failed."""
