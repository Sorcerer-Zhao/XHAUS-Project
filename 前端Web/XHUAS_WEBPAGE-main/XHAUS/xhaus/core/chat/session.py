"""OpenClaw chat session — send prompts and collect streamed replies."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable

from xhaus.core.connector.gateway_ws import GatewayWsError
from xhaus.core.connector.openclaw import OpenClawWebSocketConnector

logger = logging.getLogger(__name__)

DEFAULT_CHAT_TIMEOUT_S = 300.0


def _extract_message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


class OpenClawChatSession:
    """Thin chat layer over an already-connected OpenClawWebSocketConnector."""

    def __init__(self, connector: OpenClawWebSocketConnector) -> None:
        self._connector = connector

    @property
    def session_key(self) -> str:
        return self._connector.session_key

    @property
    def agent_id(self) -> str:
        return self._connector.agent_id

    @property
    def granted_scopes(self) -> list[str]:
        return self._connector.granted_scopes()

    def send(
        self,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
        timeout: float = DEFAULT_CHAT_TIMEOUT_S,
    ) -> str:
        """
        Send user message via chat.send; stream deltas; return final assistant text.
        """
        text = message.strip()
        if not text:
            raise GatewayWsError("消息不能为空")

        run_id = str(uuid.uuid4())
        done: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=1)
        accumulated = ""
        last_snapshot = ""

        def on_event(frame: dict) -> None:
            nonlocal accumulated, last_snapshot
            if frame.get("event") != "chat":
                return
            payload = frame.get("payload")
            if not isinstance(payload, dict):
                return
            if payload.get("runId") != run_id:
                return

            state = payload.get("state")
            if state == "delta":
                delta = payload.get("deltaText")
                if isinstance(delta, str) and delta:
                    accumulated += delta
                    if on_delta:
                        on_delta(delta)
                else:
                    snapshot = _extract_message_text(payload.get("message"))
                    if snapshot:
                        if payload.get("replace") or not snapshot.startswith(
                            last_snapshot
                        ):
                            chunk = snapshot
                        else:
                            chunk = snapshot[len(last_snapshot) :]
                        last_snapshot = snapshot
                        if chunk:
                            accumulated += chunk
                            if on_delta:
                                on_delta(chunk)
            elif state == "final":
                final_text = _extract_message_text(payload.get("message"))
                if final_text:
                    accumulated = final_text
                done.put(("final", accumulated))
            elif state == "error":
                err = payload.get("errorMessage") or "对话出错"
                done.put(("error", str(err)))
            elif state == "aborted":
                done.put(("aborted", accumulated or "对话已中止"))

        client = self._connector.ws_client
        if client is None:
            raise GatewayWsError("WebSocket 未连接")

        client.add_event_handler(on_event)
        try:
            self._connector.send_chat(text, run_id=run_id)
            try:
                kind, value = done.get(timeout=timeout)
            except queue.Empty as exc:
                raise GatewayWsError(f"等待回复超时（{timeout}s）") from exc

            if kind == "error":
                raise GatewayWsError(value or "对话出错")
            if kind == "aborted":
                return value or ""
            return value or accumulated
        finally:
            client.remove_event_handler(on_event)

    def close(self) -> None:
        self._connector.disconnect()
