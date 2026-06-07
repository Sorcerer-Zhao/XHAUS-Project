"""Gateway connection wait/retry — decoupled from CLI presentation."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from xhaus.core.connector.gateway_ws import GatewayWsError
from xhaus.core.connector.openclaw import OpenClawWebSocketConnector
from xhaus.core.device_pairing import PairingRequiredError, is_pairing_required_error

logger = logging.getLogger(__name__)

DEFAULT_RETRY_INTERVAL_S = 1.0


def wait_for_gateway(
    url: str,
    *,
    token: str | None = None,
    agent_id: str = "hausmeister",
    retry_interval: float = DEFAULT_RETRY_INTERVAL_S,
    on_retry: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    stop_on_pairing: bool = False,
) -> OpenClawWebSocketConnector:
    """
    Block until Gateway WebSocket handshake succeeds with chat permissions.

    Raises GatewayWsError if should_stop() returns True while still failing.
    """
    last_error = "未知错误"
    attempt = 0

    while True:
        if should_stop and should_stop():
            raise GatewayWsError(f"连接已取消: {last_error}")

        attempt += 1
        connector = OpenClawWebSocketConnector(
            url,
            token=token,
            agent_id=agent_id,
            connection_profile="chat",
        )
        try:
            connector.connect()
            if connector.can_chat():
                return connector
            last_error = (
                "已连接但缺少 operator.write 权限，无法对话"
                f"（granted: {connector.granted_scopes()}）"
            )
            connector.disconnect()
        except GatewayWsError as exc:
            last_error = str(exc)
            if is_pairing_required_error(last_error):
                if stop_on_pairing:
                    connector.disconnect()
                    raise PairingRequiredError(last_error) from exc
                last_error += " — 等待设备配对批准"
            connector.disconnect()
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            connector.disconnect()

        if on_retry:
            on_retry(last_error)
        else:
            logger.debug("gateway connect attempt %s failed: %s", attempt, last_error)

        time.sleep(retry_interval)
