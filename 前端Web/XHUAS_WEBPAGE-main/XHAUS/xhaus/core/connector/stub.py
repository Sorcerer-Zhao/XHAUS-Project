"""Stub runtime connector for development and bridge demos (no real network)."""

from __future__ import annotations

from collections import deque

from xhaus.core.bridge.models import BridgeMessage, MessageRole
from xhaus.core.connector.protocol import RuntimeConnector


class StubRuntimeConnector(RuntimeConnector):
    """
    In-memory connector that echoes user messages as assistant replies.
    Does not implement OpenClaw protocol.
    """

    def __init__(self, *, endpoint: str = "stub://local") -> None:
        self._endpoint = endpoint
        self._connected = False
        self._inbox: deque[BridgeMessage] = deque()
        self._outbox: deque[BridgeMessage] = deque()

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._inbox.clear()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def send(self, message: BridgeMessage) -> None:
        if not self._connected:
            raise ConnectionError("stub runtime not connected")
        self._outbox.append(message)
        # Simulate runtime processing → assistant reply queued for receive()
        reply = BridgeMessage(
            content=f"[stub-runtime] echo: {message.content}",
            role=MessageRole.ASSISTANT,
            metadata={"in_reply_to": message.id, "stub": True},
        )
        self._inbox.append(reply)

    def receive(self) -> BridgeMessage | None:
        if not self._connected:
            return None
        if not self._inbox:
            return None
        return self._inbox.popleft()

    def runtime_info(self) -> dict:
        return {
            "connector": "StubRuntimeConnector",
            "endpoint": self._endpoint,
            "pending_replies": len(self._inbox),
        }
