#!/usr/bin/env python3
"""JSON-lines bridge used by the web/miniprogram backend.

It keeps the browser-facing Node service thin while reusing XHAUS' own
OpenClaw Gateway connector, including device identity signing and pairing
diagnostics.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from xhaus.core.activation import resolve_gateway_token
from xhaus.core.chat.session import OpenClawChatSession
from xhaus.core.connector.gateway_ws import GatewayWsError
from xhaus.core.connector.openclaw import OpenClawWebSocketConnector
from xhaus.core.device_pairing import is_pairing_required_error


def emit(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def normalize_ws_url(value: str) -> str:
    url = value.strip()
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    return url


def openclaw_config_path() -> Path:
    override = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    state_dir = os.environ.get("OPENCLAW_STATE_DIR", "").strip()
    root = Path(state_dir).expanduser() if state_dir else Path.home() / ".openclaw"
    return root / "openclaw.json"


def load_openclaw_config() -> dict[str, Any]:
    path = openclaw_config_path()
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_gateway_url(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("gateway_url") or "").strip()
    env_url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip()
    if explicit or env_url:
        return normalize_ws_url(explicit or env_url)

    config = load_openclaw_config()
    gateway = config.get("gateway") if isinstance(config.get("gateway"), dict) else {}
    configured_url = str(gateway.get("url") or "").strip()
    if configured_url:
        return normalize_ws_url(configured_url)

    port = gateway.get("port", 18789)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 18789

    host = str(gateway.get("host") or gateway.get("hostname") or "127.0.0.1").strip()
    if not host or host in {"0.0.0.0", "::", "*"}:
        host = "127.0.0.1"
    return f"ws://{host}:{port}"


def resolve_agent_id(payload: dict[str, Any]) -> str:
    return (
        str(payload.get("agent_id") or payload.get("agent") or "").strip()
        or os.environ.get("XHAUS_AGENT_ID", "").strip()
        or "hausmeister"
    )


def pairing_hint(message: str, websocket_url: str) -> str:
    lower = message.lower()
    if is_pairing_required_error(message) or "operator.write" in lower:
        return (
            "OpenClaw Gateway 已连接，但当前设备缺少 operator.write 对话权限。"
            f"请在运行 Gateway 的机器上执行：openclaw devices approve --latest --url {websocket_url}，"
            "然后刷新页面重试。"
        )
    return message


def connect(payload: dict[str, Any]) -> tuple[OpenClawWebSocketConnector, str]:
    websocket_url = resolve_gateway_url(payload)
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip() or resolve_gateway_token()
    connector = OpenClawWebSocketConnector(
        websocket_url,
        token=token,
        agent_id=resolve_agent_id(payload),
        connection_profile="chat",
    )
    connector.connect()
    return connector, websocket_url


def run_ping(payload: dict[str, Any]) -> int:
    connector: OpenClawWebSocketConnector | None = None
    websocket_url = resolve_gateway_url(payload)
    try:
        connector, websocket_url = connect(payload)
        scopes = connector.granted_scopes()
        writable = connector.can_chat()
        emit(
            "status",
            ok=True,
            writable=writable,
            transport="gateway",
            url=websocket_url,
            scopes=scopes,
            detail="Gateway ready" if writable else pairing_hint("missing operator.write", websocket_url),
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        emit(
            "status",
            ok=False,
            writable=False,
            transport="gateway",
            url=websocket_url,
            detail=pairing_hint(str(exc), websocket_url),
        )
        return 1
    finally:
        if connector:
            connector.disconnect()


def run_chat(payload: dict[str, Any]) -> int:
    connector: OpenClawWebSocketConnector | None = None
    websocket_url = resolve_gateway_url(payload)
    try:
        message = str(payload.get("message") or "").strip()
        if not message:
            raise GatewayWsError("消息不能为空")

        connector, websocket_url = connect(payload)
        if not connector.can_chat():
            raise GatewayWsError(
                "缺少 operator.write 权限，无法发送对话"
                f"（granted: {connector.granted_scopes()}）"
            )

        session = OpenClawChatSession(connector)

        def on_delta(delta: str) -> None:
            emit("delta", text=delta)

        final_text = session.send(
            message,
            on_delta=on_delta,
            timeout=float(payload.get("timeout") or 300),
        )
        emit("done", text=final_text)
        return 0
    except Exception as exc:  # noqa: BLE001
        emit("error", message=pairing_hint(str(exc), websocket_url))
        return 2
    finally:
        if connector:
            connector.disconnect()


def main() -> int:
    payload = read_payload()
    mode = str(payload.get("mode") or "chat")
    if mode == "ping":
        return run_ping(payload)
    return run_chat(payload)


if __name__ == "__main__":
    raise SystemExit(main())
