"""Frontend adapter hooks for CLI / Web / App / Mini Program."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from xhaus.core.bridge.models import BridgeMessage, BridgeStatus


class FrontendAdapter(ABC):
    """
    Unified entry for any frontend channel.
    Bridge forwards runtime messages and status updates here.
    """

    @abstractmethod
    def on_outbound(self, message: BridgeMessage) -> None:
        """User or frontend sent a message (optional tap before runtime)."""

    @abstractmethod
    def on_inbound(self, message: BridgeMessage) -> None:
        """Message received from runtime via bridge."""

    @abstractmethod
    def on_status(self, status: BridgeStatus) -> None:
        """Bridge state changed."""

    @abstractmethod
    def on_error(self, error: str) -> None:
        """Non-fatal bridge error notification."""


class CallbackFrontendAdapter(FrontendAdapter):
    """Lightweight adapter using callables — useful for CLI demos."""

    def __init__(
        self,
        *,
        on_inbound: Callable[[BridgeMessage], None] | None = None,
        on_outbound: Callable[[BridgeMessage], None] | None = None,
        on_status: Callable[[BridgeStatus], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._on_inbound = on_inbound
        self._on_outbound = on_outbound
        self._on_status = on_status
        self._on_error = on_error

    def on_outbound(self, message: BridgeMessage) -> None:
        if self._on_outbound:
            self._on_outbound(message)

    def on_inbound(self, message: BridgeMessage) -> None:
        if self._on_inbound:
            self._on_inbound(message)

    def on_status(self, status: BridgeStatus) -> None:
        if self._on_status:
            self._on_status(status)

    def on_error(self, error: str) -> None:
        if self._on_error:
            self._on_error(error)
