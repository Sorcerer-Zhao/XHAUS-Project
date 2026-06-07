"""CLI console chat with OpenClaw Gateway."""

from __future__ import annotations

import sys
import threading

from xhaus.cli.device_pairing import run_device_pairing_guide
from xhaus.cli.line_input import read_line
from xhaus.cli.spinner import LoadingSpinner
from xhaus.core.activation import resolve_agent_id, resolve_gateway_token
from xhaus.core.chat import OpenClawChatSession, wait_for_gateway
from xhaus.core.connector.gateway_ws import GatewayWsError
from xhaus.core.device_pairing import PairingRequiredError

_EXIT_COMMANDS = frozenset({"/exit", "/quit", "exit", "quit", "q"})


def _connect_with_spinner(
    websocket_url: str,
    *,
    token: str | None,
    agent_id: str,
    pairing_guide: bool = True,
) -> OpenClawChatSession:
    cancel = threading.Event()
    pairing_attempted = False

    while True:
        spinner = LoadingSpinner("正在连接 OpenClaw WebSocket…")

        def on_retry(error: str) -> None:
            spinner.set_detail(error)

        def should_stop() -> bool:
            return cancel.is_set()

        try:
            with spinner:
                connector = wait_for_gateway(
                    websocket_url,
                    token=token,
                    agent_id=agent_id,
                    on_retry=on_retry,
                    should_stop=should_stop,
                    stop_on_pairing=pairing_guide and not pairing_attempted,
                )
            return OpenClawChatSession(connector)
        except KeyboardInterrupt:
            cancel.set()
            raise
        except PairingRequiredError:
            if not pairing_guide or pairing_attempted:
                raise GatewayWsError(
                    "设备仍未配对。请执行 openclaw devices approve --latest"
                ) from None
            pairing_attempted = True
            run_device_pairing_guide(websocket_url, token=token)


def run_console_chat(
    websocket_url: str,
    *,
    agent_id: str | None = None,
    token: str | None = None,
) -> None:
    """
    Wait until Gateway is reachable, then run an interactive console chat loop.
    """
    agent = agent_id or resolve_agent_id()
    auth = token if token is not None else resolve_gateway_token()

    print()
    print("  ── 控制台对话 ──")
    print(f"  WebSocket : {websocket_url}")
    print(f"  Agent     : {agent}")
    print("  输入 /exit 或 Ctrl+C 退出")
    print()

    try:
        session = _connect_with_spinner(
            websocket_url,
            token=auth,
            agent_id=agent,
        )
    except KeyboardInterrupt:
        print("\n  已取消连接。")
        return
    except GatewayWsError as exc:
        print(f"  ✗ 无法连接: {exc}")
        return

    scopes = session.granted_scopes
    print(f"  ✓ 已连接（session: {session.session_key}）")
    if scopes:
        print(f"  · scopes: {', '.join(scopes)}")
    print()

    try:
        while True:
            try:
                user_input = read_line("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  再见。")
                break

            if not user_input:
                continue
            if user_input.lower() in _EXIT_COMMANDS:
                print("  再见。")
                break

            print("OpenClaw: ", end="", flush=True)
            streamed = False

            def on_delta(chunk: str) -> None:
                nonlocal streamed
                streamed = True
                sys.stdout.write(chunk)
                sys.stdout.flush()

            try:
                session.send(user_input, on_delta=on_delta)
                if streamed:
                    print()
                else:
                    print("(无回复)")
            except GatewayWsError as exc:
                print(f"\n  [错误] {exc}")
            except Exception as exc:  # noqa: BLE001
                print(f"\n  [错误] {exc}")
    finally:
        session.close()
