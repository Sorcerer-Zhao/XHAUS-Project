"""Low-level OpenClaw Gateway WebSocket client (protocol v4)."""

from __future__ import annotations

import json
import logging
import queue
import ssl
import sys
import threading
import uuid
from collections.abc import Callable
from typing import Any, Literal

from xhaus import __title__, __version__
from xhaus.core.connector.device_identity import (
    DeviceAuthToken,
    DeviceIdentity,
    build_device_connect_params,
    load_device_auth_token,
    load_device_identity,
    resolve_connect_auth,
)

logger = logging.getLogger(__name__)

GATEWAY_PROTOCOL_VERSION = 4
DEFAULT_CHALLENGE_TIMEOUT_S = 15.0
DEFAULT_REQUEST_TIMEOUT_S = 30.0
DEFAULT_EVENT_QUEUE_SIZE = 512

ConnectionProfile = Literal["probe", "chat"]

_CONNECT_PROFILES: dict[ConnectionProfile, dict[str, Any]] = {
    "probe": {
        "id": "openclaw-probe",
        "mode": "probe",
        "scopes": ["operator.read", "operator.write", "operator.admin"],
    },
    "chat": {
        "id": "cli",
        "mode": "cli",
        "scopes": ["operator.read", "operator.write"],
    },
}


class GatewayWsError(Exception):
    """WebSocket or Gateway RPC failure."""

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


class GatewayWsClient:
    """
    Minimal Gateway WS client: connect.challenge → connect → JSON-RPC req/res.
    Not tied to MessageBridge; used by OpenClawWebSocketConnector.
    """

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        role: str = "operator",
        scopes: list[str] | None = None,
        connection_profile: ConnectionProfile = "probe",
    ) -> None:
        self._url = url
        self._token = token
        self._role = role
        profile = _CONNECT_PROFILES.get(connection_profile, _CONNECT_PROFILES["probe"])
        self._connection_profile = connection_profile
        self._client_id = str(profile["id"])
        self._client_mode = str(profile["mode"])
        self._scopes = scopes or list(profile["scopes"])
        self._ws: Any = None
        self._recv_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending: dict[str, queue.Queue[Any]] = {}
        self._challenge_queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=DEFAULT_EVENT_QUEUE_SIZE
        )
        self._event_handlers: list[Callable[[dict[str, Any]], None]] = []
        self._connected = False
        self._hello: dict[str, Any] | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    @property
    def hello(self) -> dict[str, Any] | None:
        return self._hello

    def connect(self, *, timeout: float = DEFAULT_CHALLENGE_TIMEOUT_S) -> dict[str, Any]:
        """Open WebSocket, complete handshake, return hello-ok payload."""
        try:
            import websocket  # type: ignore[import-untyped]
        except ImportError as exc:
            raise GatewayWsError(
                "缺少依赖 websocket-client，请执行: pip install websocket-client"
            ) from exc

        sslopt = None
        if self._url.startswith("wss://"):
            sslopt = {"cert_reqs": ssl.CERT_NONE}

        try:
            self._ws = websocket.create_connection(
                self._url,
                timeout=timeout,
                sslopt=sslopt,
            )
            # Keep the chat session alive while the user is idle at the prompt.
            self._ws.settimeout(None)
        except OSError as exc:
            raise GatewayWsError(f"无法连接 WebSocket: {exc}") from exc

        self._stop.clear()
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        try:
            nonce = self._challenge_queue.get(timeout=timeout)
        except queue.Empty as exc:
            self.close()
            raise GatewayWsError(
                f"连接预检超时：未收到 connect.challenge（{timeout}s）"
            ) from exc

        params = self._build_connect_params(nonce)

        hello = self.request("connect", params, timeout=timeout)
        if not isinstance(hello, dict):
            raise GatewayWsError("connect 响应格式无效")
        self._hello = hello
        self._connected = True
        return hello

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
    ) -> Any:
        if not self._ws:
            raise GatewayWsError("WebSocket 未连接")

        req_id = str(uuid.uuid4())
        frame = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        response_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._pending[req_id] = response_queue

        try:
            self._ws.send(json.dumps(frame))
            msg = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise GatewayWsError(f"请求超时: {method}（{timeout}s）") from exc
        finally:
            self._pending.pop(req_id, None)

        if isinstance(msg, GatewayWsError):
            raise msg
        return msg

    def emit_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """Fire-and-forget event frame (no response)."""
        if not self._ws:
            raise GatewayWsError("WebSocket 未连接")
        frame: dict[str, Any] = {"type": "event", "event": event}
        if payload is not None:
            frame["payload"] = payload
        self._ws.send(json.dumps(frame))

    def granted_scopes(self) -> list[str]:
        auth = (self._hello or {}).get("auth") or {}
        scopes = auth.get("scopes") if isinstance(auth, dict) else []
        return list(scopes) if isinstance(scopes, list) else []

    def has_scope(self, scope: str) -> bool:
        scopes = self.granted_scopes()
        if "operator.admin" in scopes:
            return True
        if scope == "operator.read":
            return "operator.read" in scopes or "operator.write" in scopes
        return scope in scopes

    def add_event_handler(
        self, handler: Callable[[dict[str, Any]], None]
    ) -> None:
        self._event_handlers.append(handler)

    def remove_event_handler(
        self, handler: Callable[[dict[str, Any]], None]
    ) -> None:
        try:
            self._event_handlers.remove(handler)
        except ValueError:
            pass

    def poll_event(self, *, timeout: float = 0.0) -> dict[str, Any] | None:
        try:
            if timeout > 0:
                return self._event_queue.get(timeout=timeout)
            return self._event_queue.get_nowait()
        except queue.Empty:
            return None

    def _build_connect_params(self, nonce: str) -> dict[str, Any]:
        scopes = list(self._scopes)
        identity: DeviceIdentity | None = None
        device_auth: DeviceAuthToken | None = None

        if self._connection_profile == "chat":
            identity = load_device_identity()
            device_auth = load_device_auth_token(self._role)
            if device_auth and device_auth.scopes:
                scopes = list(device_auth.scopes)

        auth_dict, signature_token, preferred_scopes = resolve_connect_auth(
            gateway_token=self._token,
            device_auth=device_auth,
        )
        if preferred_scopes:
            scopes = list(preferred_scopes)

        params: dict[str, Any] = {
            "minProtocol": GATEWAY_PROTOCOL_VERSION,
            "maxProtocol": GATEWAY_PROTOCOL_VERSION,
            "client": {
                "id": self._client_id,
                "displayName": __title__,
                "version": __version__,
                "platform": sys.platform,
                "mode": self._client_mode,
            },
            "role": self._role,
            "scopes": scopes,
            "caps": [],
        }
        if auth_dict:
            params["auth"] = auth_dict

        if identity:
            params["device"] = build_device_connect_params(
                identity,
                nonce=nonce,
                client_id=self._client_id,
                client_mode=self._client_mode,
                role=self._role,
                scopes=scopes,
                signature_token=signature_token,
                platform=sys.platform,
            )
        return params

    def close(self) -> None:
        self._connected = False
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except OSError:
                pass
            self._ws = None

    def _recv_loop(self) -> None:
        timeout_exc: type[BaseException] | tuple[type[BaseException], ...] = ()
        try:
            from websocket import WebSocketTimeoutException

            timeout_exc = WebSocketTimeoutException
        except ImportError:
            pass

        while not self._stop.is_set() and self._ws:
            try:
                raw = self._ws.recv()
            except timeout_exc:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                logger.debug("gateway ws recv closed")
                break
            if not raw:
                continue
            try:
                self._handle_message(raw)
            except Exception as exc:  # noqa: BLE001
                logger.debug("gateway ws parse error: %s", exc)

    def _handle_message(self, raw: str) -> None:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return

        if parsed.get("type") == "event":
            event = parsed.get("event")
            if event == "connect.challenge":
                payload = parsed.get("payload") or {}
                nonce = payload.get("nonce") if isinstance(payload, dict) else None
                if isinstance(nonce, str) and nonce.strip():
                    try:
                        self._challenge_queue.put_nowait(nonce.strip())
                    except queue.Full:
                        pass
                return
            self._dispatch_event(parsed)
            return

        if parsed.get("type") != "res":
            return

        req_id = parsed.get("id")
        if not isinstance(req_id, str):
            return

        q = self._pending.get(req_id)
        if q is None:
            return

        if parsed.get("ok"):
            q.put(parsed.get("payload"))
        else:
            err = parsed.get("error") or {}
            message = err.get("message", "unknown error") if isinstance(err, dict) else str(err)
            code = err.get("code") if isinstance(err, dict) else None
            q.put(GatewayWsError(str(message), code=code, details=err))

    def _dispatch_event(self, frame: dict[str, Any]) -> None:
        try:
            self._event_queue.put_nowait(frame)
        except queue.Full:
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._event_queue.put_nowait(frame)
            except queue.Full:
                logger.debug("gateway event queue full, dropping frame")

        for handler in list(self._event_handlers):
            try:
                handler(frame)
            except Exception as exc:  # noqa: BLE001
                logger.debug("gateway event handler error: %s", exc)
