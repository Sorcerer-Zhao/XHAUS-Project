"""Bridge layer — message flow between frontends and runtime."""

from xhaus.core.bridge.bridge import MessageBridge
from xhaus.core.bridge.errors import (
    BridgeAlreadyClosedError,
    BridgeConnectionError,
    BridgeError,
    BridgeMessageError,
    BridgeNotMountedError,
    BridgeStateError,
)
from xhaus.core.bridge.frontend import CallbackFrontendAdapter, FrontendAdapter
from xhaus.core.bridge.models import BridgeMessage, BridgeState, BridgeStatus, MessageRole

__all__ = [
    "BridgeAlreadyClosedError",
    "BridgeConnectionError",
    "BridgeError",
    "BridgeMessage",
    "BridgeMessageError",
    "BridgeNotMountedError",
    "BridgeState",
    "BridgeStateError",
    "BridgeStatus",
    "CallbackFrontendAdapter",
    "FrontendAdapter",
    "MessageBridge",
    "MessageRole",
]
