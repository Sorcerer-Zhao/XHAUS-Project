"""OpenClaw Gateway WebSocket runtime connector."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from xhaus.core.bridge.models import BridgeMessage, MessageRole
from xhaus.core.connector.gateway_ws import (
    ConnectionProfile,
    GatewayWsClient,
    GatewayWsError,
)
from xhaus.core.connector.protocol import RuntimeConnector
from xhaus.config.models import PROFILE_DOCUMENT_ORDER
from xhaus.core.payload import MountPayload

logger = logging.getLogger(__name__)

MOUNT_METHOD = "xhaus.mount"
# Unregistered methods default to operator.admin in OpenClaw scope policy.
_MOUNT_FALLBACK_MARKERS = (
    "unknown method",
    "missing scope: operator.admin",
)


class OpenClawWebSocketConnector(RuntimeConnector):
    """
    Runtime connector for OpenClaw Gateway over WebSocket.

    OpenClaw protocol details are isolated here; MessageBridge stays agnostic.
    """

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        agent_id: str = "hausmeister",
        connection_profile: ConnectionProfile = "probe",
        session_key: str | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._agent_id = agent_id
        self._connection_profile = connection_profile
        self._session_key = session_key or resolve_session_key(agent_id)
        self._client: GatewayWsClient | None = None
        self._last_mount_response: dict[str, Any] | None = None
        self._active_run_id: str | None = None

    @property
    def endpoint(self) -> str:
        return self._url

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def last_mount_response(self) -> dict[str, Any] | None:
        return self._last_mount_response

    @property
    def session_key(self) -> str:
        return self._session_key

    @property
    def connection_profile(self) -> ConnectionProfile:
        return self._connection_profile

    @property
    def ws_client(self) -> GatewayWsClient | None:
        return self._client

    def granted_scopes(self) -> list[str]:
        if not self._client:
            return []
        return self._client.granted_scopes()

    def can_chat(self) -> bool:
        if not self.is_connected or not self._client:
            return False
        return self._client.has_scope("operator.write")

    def connect(self) -> None:
        self._client = GatewayWsClient(
            self._url,
            token=self._token,
            connection_profile=self._connection_profile,
        )
        self._client.connect()

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    def precheck(self) -> dict[str, Any]:
        """Connect handshake only; used before mount to validate the endpoint."""
        self.connect()
        hello = self._client.hello if self._client else {}
        return hello or {}

    def send_mount(self, payload: MountPayload) -> dict[str, Any]:
        """Send unified xhaus.mount payload; may raise GatewayWsError."""
        if not self._client or not self.is_connected:
            raise GatewayWsError("Runtime 未连接，无法发送挂载载荷")

        try:
            result = self._client.request(MOUNT_METHOD, payload.to_dict())
            if isinstance(result, dict):
                self._last_mount_response = result
                return result
            self._last_mount_response = {"ok": True, "raw": result}
            return self._last_mount_response
        except GatewayWsError as exc:
            msg = str(exc).lower()
            if not any(marker in msg for marker in _MOUNT_FALLBACK_MARKERS):
                raise
            logger.info("xhaus.mount 不可用（未注册或权限不足），尝试回退方案")
            return self._mount_fallback(payload)

    def _mount_fallback(self, payload: MountPayload) -> dict[str, Any]:
        """Fallback: event broadcast + agents.files.set when scopes allow."""
        notes: list[str] = []
        try:
            self._client.emit_event("xhaus.mount", payload.to_dict())
            notes.append("已通过 xhaus.mount 事件广播载荷")
        except GatewayWsError as exc:
            notes.append(f"事件广播跳过: {exc}")

        scopes = self._client.granted_scopes()
        if "operator.admin" not in scopes:
            return {
                "ok": True,
                "mode": "degraded",
                "method": "precheck+payload",
                "granted_scopes": scopes,
                "notes": notes,
                "skills_in_payload": len(payload.skills),
                "skills_note": (
                    "预检已通过，载荷已准备；完整写入需 Gateway 支持 xhaus.mount "
                    "或具备 operator.admin 的 Token"
                ),
            }

        try:
            file_result = self._apply_profile_files(payload)
            file_result["mode"] = "fallback:agents.files.set"
            file_result["notes"] = notes + file_result.get("notes", [])
            return file_result
        except GatewayWsError:
            if notes:
                return {
                    "ok": True,
                    "mode": "degraded",
                    "method": "xhaus.mount.event",
                    "notes": notes,
                    "skills_in_payload": len(payload.skills),
                }
            raise

    def _apply_profile_files(self, payload: MountPayload) -> dict[str, Any]:
        """Push profile documents via agents.files.set when xhaus.mount is unavailable."""
        if not self._client:
            raise GatewayWsError("Runtime 未连接")

        profile = payload.profile
        documents = profile.get("documents") or {}
        filenames = profile.get("filenames") or {}
        applied: list[str] = []
        errors: list[str] = []

        for kind in PROFILE_DOCUMENT_ORDER:
            key = kind.value
            content = documents.get(key)
            filename = filenames.get(key, kind.filename)
            if content is None:
                errors.append(f"跳过空文档: {filename}")
                continue
            try:
                self._client.request(
                    "agents.files.set",
                    {
                        "agentId": self._agent_id,
                        "name": filename,
                        "content": content,
                    },
                )
                applied.append(filename)
            except GatewayWsError as exc:
                errors.append(f"{filename}: {exc}")

        notes: list[str] = []
        result = {
            "ok": len(errors) == 0,
            "agentId": self._agent_id,
            "applied": applied,
            "errors": errors,
            "skills_in_payload": len(payload.skills),
            "skills_note": "Skills 已打入载荷；待 Gateway 支持 xhaus.mount 后自动同步",
            "notes": notes,
        }
        self._last_mount_response = result
        if errors and not applied:
            raise GatewayWsError(
                "Profile 回退写入失败: " + "; ".join(errors)
            )
        return result

    def send_chat(self, message: str, *, run_id: str | None = None) -> dict[str, Any]:
        """Send chat.send RPC; returns Gateway ack payload."""
        if not self._client or not self.is_connected:
            raise GatewayWsError("Runtime 未连接")
        if not self.can_chat():
            raise GatewayWsError(
                "缺少 operator.write 权限，无法发送对话"
                f"（granted: {self.granted_scopes()}）"
            )

        run_id = run_id or str(uuid.uuid4())
        self._active_run_id = run_id
        result = self._client.request(
            "chat.send",
            {
                "sessionKey": self._session_key,
                "message": message,
                "idempotencyKey": run_id,
                "agentId": self._agent_id,
            },
        )
        if not isinstance(result, dict):
            return {"runId": run_id, "status": "started"}
        return result

    def send(self, message: BridgeMessage) -> None:
        """Forward user message via chat.send."""
        self.send_chat(message.content, run_id=message.id)

    def receive(self) -> BridgeMessage | None:
        """Poll one chat event from the Gateway event queue."""
        if not self._client:
            return None
        frame = self._client.poll_event()
        if not frame or frame.get("event") != "chat":
            return None
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return None

        state = payload.get("state")
        text = ""
        if state == "delta":
            delta = payload.get("deltaText")
            if isinstance(delta, str):
                text = delta
            else:
                msg = payload.get("message")
                if isinstance(msg, dict):
                    text = _extract_assistant_text(msg)
        elif state in ("final", "error", "aborted"):
            msg = payload.get("message")
            if isinstance(msg, dict):
                text = _extract_assistant_text(msg)
            elif state == "error":
                text = str(payload.get("errorMessage") or "对话出错")

        role = MessageRole.ASSISTANT
        if state == "error":
            role = MessageRole.RUNTIME

        return BridgeMessage(
            content=text,
            role=role,
            metadata={
                "event": "chat",
                "state": state,
                "runId": payload.get("runId"),
                "sessionKey": payload.get("sessionKey"),
            },
        )

    def runtime_info(self) -> dict[str, Any]:
        base = {
            "connector": "OpenClawWebSocketConnector",
            "endpoint": self._url,
            "agentId": self._agent_id,
        }
        if self._client and self._client.hello:
            server = self._client.hello.get("server") or {}
            base["server_version"] = server.get("version")
        base["sessionKey"] = self._session_key
        base["connection_profile"] = self._connection_profile
        base["granted_scopes"] = self.granted_scopes()
        return base


def resolve_session_key(agent_id: str) -> str:
    override = os.environ.get("XHAUS_SESSION_KEY", "").strip()
    if override:
        return override
    return f"agent:{agent_id}:main"


def _extract_assistant_text(message: dict[str, Any]) -> str:
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
