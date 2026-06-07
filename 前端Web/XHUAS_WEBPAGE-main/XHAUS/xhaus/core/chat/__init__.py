"""OpenClaw console chat — session and connection helpers."""

from xhaus.core.chat.session import OpenClawChatSession
from xhaus.core.connection import wait_for_gateway

__all__ = ["OpenClawChatSession", "wait_for_gateway"]
