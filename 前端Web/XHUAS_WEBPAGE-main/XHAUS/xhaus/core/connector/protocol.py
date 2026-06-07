"""Runtime connector abstraction — decoupled from OpenClaw protocol details."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from xhaus.core.bridge.models import BridgeMessage


class RuntimeConnector(ABC):
    """
    Adapter to a runtime backend (e.g. OpenClaw WebSocket).

    Bridge talks only through this interface; OpenClaw specifics stay in subclasses.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish transport to the runtime."""

    @abstractmethod
    def disconnect(self) -> None:
        """ Tear down transport."""

    @abstractmethod
    def send(self, message: BridgeMessage) -> None:
        """Send a message to the runtime."""

    @abstractmethod
    def receive(self) -> BridgeMessage | None:
        """
        Poll one message from the runtime.
        Returns None when no message is available (non-blocking contract).
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the transport is active."""

    def runtime_info(self) -> dict[str, Any]:
        """Optional metadata about the underlying runtime (for status())."""
        return {"connector": self.__class__.__name__}
