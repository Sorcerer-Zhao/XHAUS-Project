"""MessageBridge — unified message flow between frontends and runtime."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from xhaus.core.bridge.errors import (
    BridgeAlreadyClosedError,
    BridgeConnectionError,
    BridgeMessageError,
    BridgeNotMountedError,
    BridgeStateError,
)
from xhaus.core.bridge.models import (
    _RECEIVABLE_STATES,
    _SENDABLE_STATES,
    BridgeMessage,
    BridgeState,
    BridgeStatus,
)
from xhaus.core.connector.protocol import RuntimeConnector

if TYPE_CHECKING:
    from xhaus.core.bridge.frontend import FrontendAdapter

logger = logging.getLogger(__name__)


class MessageBridge:
    """
    Middle layer: Frontend → Bridge → RuntimeConnector → OpenClaw (future).

    Does not perform inference, persona, or skills logic.
    """

    def __init__(self, *, name: str = "xhaus-bridge") -> None:
        self._name = name
        self._state = BridgeState.DISCONNECTED
        self._connector: RuntimeConnector | None = None
        self._frontend: FrontendAdapter | None = None
        self._last_error: str | None = None
        self._message_count_in = 0
        self._message_count_out = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> BridgeState:
        return self._state

    def _set_state(self, new_state: BridgeState) -> None:
        old = self._state
        self._state = new_state
        if old != new_state:
            logger.debug("bridge %s: %s → %s", self._name, old.value, new_state.value)
            self._notify_status()

    def _notify_status(self) -> None:
        if self._frontend:
            try:
                self._frontend.on_status(self.status())
            except Exception as exc:  # noqa: BLE001 — frontend must not break bridge
                logger.warning("frontend on_status failed: %s", exc)

    def _notify_error(self, message: str) -> None:
        self._last_error = message
        if self._frontend:
            try:
                self._frontend.on_error(message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("frontend on_error failed: %s", exc)

    def register_frontend(self, adapter: FrontendAdapter) -> None:
        """Attach a frontend channel (CLI, Web, App, etc.)."""
        self._frontend = adapter
        self._notify_status()

    def mount(self, connector: RuntimeConnector, *, auto_connect: bool = True) -> None:
        """
        Mount a runtime connector and optionally connect immediately.
        DISCONNECTED → CONNECTED → MOUNTED
        """
        if self._state == BridgeState.CLOSED:
            raise BridgeAlreadyClosedError(
                "cannot mount on a closed bridge",
                state=self._state,
            )
        if self._state in (BridgeState.MOUNTED, BridgeState.RUNNING, BridgeState.CONNECTED):
            raise BridgeStateError(
                "runtime already mounted; close before remounting",
                state=self._state,
            )
        if self._state == BridgeState.ERROR:
            raise BridgeStateError(
                "bridge is in error state; create a new bridge or reset",
                state=self._state,
            )

        self._connector = connector

        if auto_connect:
            try:
                if not connector.is_connected:
                    connector.connect()
                self._set_state(BridgeState.CONNECTED)
            except Exception as exc:
                self._set_state(BridgeState.ERROR)
                msg = f"runtime connect failed: {exc}"
                self._notify_error(msg)
                raise BridgeConnectionError(msg, state=self._state) from exc

        self._set_state(BridgeState.MOUNTED)

    def attach(self, connector: RuntimeConnector, *, auto_connect: bool = True) -> None:
        """Alias for mount() — same behavior."""
        self.mount(connector, auto_connect=auto_connect)

    def send(self, message: BridgeMessage | str) -> BridgeMessage:
        """
        Send a message to the runtime via the mounted connector.
        MOUNTED → RUNNING on success.
        """
        if self._state == BridgeState.CLOSED:
            raise BridgeAlreadyClosedError("bridge is closed", state=self._state)

        if self._state not in _SENDABLE_STATES:
            raise BridgeNotMountedError(
                "mount a runtime connector before sending",
                state=self._state,
            )

        if self._connector is None:
            raise BridgeNotMountedError("no connector mounted", state=self._state)

        if not self._connector.is_connected:
            raise BridgeConnectionError("runtime is not connected", state=self._state)

        envelope = (
            message
            if isinstance(message, BridgeMessage)
            else BridgeMessage(content=message)
        )

        if self._frontend:
            try:
                self._frontend.on_outbound(envelope)
            except Exception as exc:  # noqa: BLE001
                logger.warning("frontend on_outbound failed: %s", exc)

        try:
            self._connector.send(envelope)
            self._message_count_out += 1
            self._set_state(BridgeState.RUNNING)
            return envelope
        except Exception as exc:
            self._set_state(BridgeState.ERROR)
            msg = f"send failed: {exc}"
            self._notify_error(msg)
            raise BridgeMessageError(msg, state=self._state) from exc

    def receive(self) -> BridgeMessage | None:
        """
        Poll one message from the runtime.
        Returns None if nothing is available.
        """
        if self._state == BridgeState.CLOSED:
            raise BridgeAlreadyClosedError("bridge is closed", state=self._state)

        if self._state not in _RECEIVABLE_STATES:
            raise BridgeNotMountedError(
                "mount a runtime connector before receiving",
                state=self._state,
            )

        if self._connector is None:
            raise BridgeNotMountedError("no connector mounted", state=self._state)

        if not self._connector.is_connected:
            raise BridgeConnectionError("runtime is not connected", state=self._state)

        try:
            message = self._connector.receive()
        except Exception as exc:
            self._set_state(BridgeState.ERROR)
            msg = f"receive failed: {exc}"
            self._notify_error(msg)
            raise BridgeMessageError(msg, state=self._state) from exc

        if message is None:
            return None

        self._message_count_in += 1
        self._set_state(BridgeState.RUNNING)

        if self._frontend:
            try:
                self._frontend.on_inbound(message)
            except Exception as exc:  # noqa: BLE001
                logger.warning("frontend on_inbound failed: %s", exc)

        return message

    def status(self) -> BridgeStatus:
        """Current bridge snapshot."""
        connector_connected = bool(
            self._connector and self._connector.is_connected
        )
        return BridgeStatus(
            state=self._state,
            mounted=self._connector is not None
            and self._state
            in (
                BridgeState.CONNECTED,
                BridgeState.MOUNTED,
                BridgeState.RUNNING,
                BridgeState.ERROR,
            ),
            connector_connected=connector_connected,
            last_error=self._last_error,
            message_count_in=self._message_count_in,
            message_count_out=self._message_count_out,
        )

    def close(self) -> None:
        """Close bridge and disconnect runtime. Idempotent with warning on repeat."""
        if self._state == BridgeState.CLOSED:
            logger.info("bridge %s: close() called while already closed", self._name)
            return

        if self._connector is not None:
            try:
                if self._connector.is_connected:
                    self._connector.disconnect()
            except Exception as exc:
                self._last_error = f"disconnect failed: {exc}"
                logger.warning("bridge disconnect error: %s", exc)

        self._connector = None
        self._set_state(BridgeState.CLOSED)

    def reset(self) -> None:
        """Return to DISCONNECTED after close (for reuse in tests)."""
        if self._state not in (BridgeState.CLOSED, BridgeState.ERROR, BridgeState.DISCONNECTED):
            self.close()
        self._state = BridgeState.DISCONNECTED
        self._last_error = None
        self._message_count_in = 0
        self._message_count_out = 0
        self._notify_status()
