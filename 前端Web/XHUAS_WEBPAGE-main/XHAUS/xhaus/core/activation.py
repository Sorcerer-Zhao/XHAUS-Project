"""XHAUS MVP activation — precheck, pack, mount, bridge (orchestration)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from xhaus.config import load_from_directory, load_preset
from xhaus.config.models import Profile
from xhaus.core.bridge.bridge import MessageBridge
from xhaus.core.bridge.models import BridgeState
from xhaus.core.connector.gateway_ws import GatewayWsError
from xhaus.core.connector.openclaw import OpenClawWebSocketConnector
from xhaus.core.openclaw_agent import find_openclaw_agent, link_skills_for_workspace
from xhaus.core.payload import build_mount_payload
from xhaus.skills import SkillManager, load_skills_default
from xhaus.skills.models import SkillLoadResult, SkillRegistry

logger = logging.getLogger(__name__)


@dataclass
class ActivationResult:
    """Outcome of the full mount + activate pipeline."""

    ok: bool
    websocket_url: str
    profile: Profile | None
    skills: SkillLoadResult | None
    bridge_state: BridgeState | None = None
    mount_mode: str | None = None
    message: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    connector: OpenClawWebSocketConnector | None = None
    bridge: MessageBridge | None = None

    def report(self) -> str:
        lines = [self.message or ("成功" if self.ok else "失败")]
        for w in self.warnings:
            lines.append(f"  [警告] {w}")
        for e in self.errors:
            lines.append(f"  [错误] {e}")
        return "\n".join(lines)


def resolve_gateway_token() -> str | None:
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if token:
        return token
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if not config_path.is_file():
        return None
    try:
        import json

        data = json.loads(config_path.read_text(encoding="utf-8"))
        return (
            data.get("gateway", {})
            .get("auth", {})
            .get("token")
        )
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def resolve_agent_id() -> str:
    return os.environ.get("XHAUS_AGENT_ID", "hausmeister").strip() or "hausmeister"


def _load_profile(
    *,
    preset_name: str | None,
    profile_path: Path | None,
) -> tuple[Profile | None, list[str], list[str]]:
    if preset_name:
        result = load_preset(preset_name)
    elif profile_path:
        result = load_from_directory(profile_path)
    else:
        return None, ["未指定 Profile"], []

    warnings = list(result.warnings)
    if result.profile is None:
        return None, list(result.errors) or ["Profile 加载失败"], warnings
    if not result.ok:
        return result.profile, list(result.errors), warnings
    return result.profile, [], warnings


def activate_xhaus(
    *,
    websocket_url: str,
    preset_name: str | None = None,
    profile_path: Path | None = None,
    role_label: str | None = None,
    profile_ok: bool = True,
    profile_errors: list[str] | None = None,
    agent_id: str | None = None,
) -> ActivationResult:
    """
    Full MVP pipeline:
    1. Load profile + skills
    2. WebSocket precheck
    3. Pack payload
    4. Send mount
    5. Mount bridge
    """
    errors: list[str] = list(profile_errors or [])
    warnings: list[str] = []

    if not profile_ok:
        return ActivationResult(
            ok=False,
            websocket_url=websocket_url,
            profile=None,
            skills=None,
            message="Profile 不完整，无法挂载",
            errors=errors or ["Profile 校验未通过"],
        )

    profile, profile_errs, profile_warns = _load_profile(
        preset_name=preset_name,
        profile_path=profile_path,
    )
    warnings.extend(profile_warns)
    if profile_errs:
        return ActivationResult(
            ok=False,
            websocket_url=websocket_url,
            profile=profile,
            skills=None,
            message="Profile 加载失败",
            errors=profile_errs,
            warnings=warnings,
        )

    skills_result = load_skills_default()
    warnings.extend(skills_result.warnings)
    if skills_result.errors:
        warnings.extend(skills_result.errors)

    token = resolve_gateway_token()
    if not token:
        warnings.append(
            "未设置 OPENCLAW_GATEWAY_TOKEN，连接可能因认证失败（可在 ~/.openclaw/openclaw.json 读取）"
        )

    resolved_agent_id = (agent_id or resolve_agent_id()).strip() or resolve_agent_id()
    agent_info = find_openclaw_agent(resolved_agent_id)
    if agent_info is not None:
        skill_warns, skill_errs = link_skills_for_workspace(agent_info.workspace)
        warnings.extend(skill_warns)
        if skill_errs:
            warnings.extend(skill_errs)

    connector: OpenClawWebSocketConnector | None = None

    try:
        connector = OpenClawWebSocketConnector(
            websocket_url,
            token=token,
            agent_id=resolved_agent_id,
        )

        print("  正在预检 WebSocket 连接…")
        hello = connector.precheck()
        server = (hello.get("server") or {}) if isinstance(hello, dict) else {}
        version = server.get("version", "unknown")
        print(f"  ✓ 预检通过 — Gateway {version}")

        payload = build_mount_payload(
            profile,
            skills_result.registry,
            role_label=role_label,
            websocket_url=websocket_url,
        )

        print("  正在发送挂载载荷（Profile + Skills）…")
        mount_response = connector.send_mount(payload)
        mount_mode = str(mount_response.get("mode") or mount_response.get("method") or "xhaus.mount")
        for key in ("skills_note", "notes"):
            val = mount_response.get(key)
            if isinstance(val, str) and val:
                warnings.append(val)
            elif isinstance(val, list):
                warnings.extend(str(v) for v in val)
        if mount_response.get("mode") == "degraded":
            warnings.append(
                "Bridge 已激活（降级模式）：预检通过，载荷已广播/准备，等待 Gateway 完整支持"
            )

        bridge = MessageBridge(name="xhaus-mvp")
        bridge.mount(connector, auto_connect=False)
        # Mount uses probe profile; console chat reconnects with cli profile.
        connector.disconnect()

        skills_n = len(skills_result.registry.enabled_skills)
        success_msg = (
            "已挂载成功 / Bridge 已激活\n"
            f"  · Profile: {profile.name}\n"
            f"  · Skills: {skills_n} 个已启用\n"
            f"  · 挂载方式: {mount_mode}\n"
            f"  · Agent: {resolved_agent_id}"
        )

        return ActivationResult(
            ok=True,
            websocket_url=websocket_url,
            profile=profile,
            skills=skills_result,
            bridge_state=bridge.state,
            mount_mode=str(mount_mode),
            message=success_msg,
            warnings=[w for w in warnings if w],
            connector=None,
            bridge=bridge,
        )

    except GatewayWsError as exc:
        if connector:
            connector.disconnect()
        return ActivationResult(
            ok=False,
            websocket_url=websocket_url,
            profile=profile,
            skills=skills_result,
            message="挂载失败",
            errors=[str(exc)],
            warnings=warnings,
        )
    except Exception as exc:  # noqa: BLE001 — MVP must not crash
        logger.exception("activation failed")
        if connector:
            connector.disconnect()
        return ActivationResult(
            ok=False,
            websocket_url=websocket_url,
            profile=profile,
            skills=skills_result,
            message="挂载过程发生未预期错误",
            errors=[str(exc)],
            warnings=warnings,
        )
