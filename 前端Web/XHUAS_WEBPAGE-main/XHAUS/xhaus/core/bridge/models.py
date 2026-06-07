"""Bridge message and state models."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BridgeState(str, Enum):
    """Lifecycle states for MessageBridge."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    MOUNTED = "mounted"
    RUNNING = "running"
    CLOSED = "closed"
    ERROR = "error"


# States that allow outbound messages
_SENDABLE_STATES: frozenset[BridgeState] = frozenset(
    {BridgeState.MOUNTED, BridgeState.RUNNING}
)

# States where receive is meaningful
_RECEIVABLE_STATES: frozenset[BridgeState] = frozenset(
    {BridgeState.MOUNTED, BridgeState.RUNNING}
)


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    RUNTIME = "runtime"


@dataclass
class BridgeMessage:
    """Unified message envelope across frontends and runtime."""

    content: str
    role: MessageRole = MessageRole.USER
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class BridgeStatus:
    """Snapshot of bridge health for frontends and logging."""

    state: BridgeState
    mounted: bool
    connector_connected: bool
    last_error: str | None = None
    message_count_in: int = 0
    message_count_out: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "mounted": self.mounted,
            "connector_connected": self.connector_connected,
            "last_error": self.last_error,
            "message_count_in": self.message_count_in,
            "message_count_out": self.message_count_out,
        }
