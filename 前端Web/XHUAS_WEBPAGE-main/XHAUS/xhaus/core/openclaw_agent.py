"""OpenClaw agent provisioning — CLI wrapper and profile sync."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from xhaus.config.models import PROFILE_DOCUMENT_ORDER
from xhaus.skills.workspace_link import link_skills_into_workspace

logger = logging.getLogger(__name__)

OPENCLAW_STATE = Path.home() / ".openclaw"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEEPSEEK_PROVIDER = "deepseek"
_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def _openclaw_command(args: list[str]) -> list[str]:
    """Resolve the OpenClaw CLI in a way that works from Python on Windows."""
    for name in ("openclaw.cmd", "openclaw.exe", "openclaw"):
        resolved = shutil.which(name)
        if resolved:
            return [resolved, *args]

    ps1 = shutil.which("openclaw.ps1")
    if ps1:
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            ps1,
            *args,
        ]

    return ["openclaw", *args]


@dataclass(frozen=True)
class OpenClawAgentInfo:
    id: str
    name: str | None
    workspace: Path
    model: str | None


@dataclass
class AgentProvisionResult:
    ok: bool
    agent_id: str
    workspace: Path | None = None
    created: bool = False
    message: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_openclaw_agent_id(value: str) -> str:
    """Match OpenClaw normalizeAgentId: lowercase slug."""
    trimmed = (value or "").strip().lower()
    if not trimmed:
        return "main"
    if _AGENT_ID_RE.match(trimmed):
        return trimmed
    slug = re.sub(r"[^a-z0-9_-]+", "-", trimmed)
    slug = slug.strip("-")[:64]
    return slug or "main"


def default_openclaw_workspace(agent_id: str) -> Path:
    """~/.openclaw/workspace-<id> — matches `openclaw agents add` convention."""
    return OPENCLAW_STATE / f"workspace-{normalize_openclaw_agent_id(agent_id)}"


def resolve_default_model() -> str:
    for agent in list_openclaw_agents():
        if agent.model:
            return agent.model
    return DEFAULT_MODEL


def list_openclaw_agents() -> list[OpenClawAgentInfo]:
    try:
        proc = subprocess.run(
            _openclaw_command(["agents", "list", "--json"]),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("openclaw agents list failed: %s", exc)
        return []

    if proc.returncode != 0:
        logger.warning("openclaw agents list: %s", proc.stderr.strip())
        return []

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    agents: list[OpenClawAgentInfo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id", "")).strip()
        if not agent_id:
            continue
        workspace_raw = item.get("workspace")
        workspace = (
            Path(str(workspace_raw)).expanduser()
            if isinstance(workspace_raw, str) and workspace_raw.strip()
            else OPENCLAW_STATE / "workspace"
        )
        name = item.get("name")
        model = item.get("model")
        agents.append(
            OpenClawAgentInfo(
                id=agent_id,
                name=str(name) if isinstance(name, str) else None,
                workspace=workspace,
                model=str(model) if isinstance(model, str) else None,
            )
        )
    return agents


def find_openclaw_agent(agent_id: str) -> OpenClawAgentInfo | None:
    needle = normalize_openclaw_agent_id(agent_id)
    for agent in list_openclaw_agents():
        if agent.id == needle:
            return agent
    return None


def preset_canonical_agent_id(preset_name: str) -> str:
    """Default OpenClaw agent id for a bundled preset (e.g. Franziska → franziska)."""
    return normalize_openclaw_agent_id(preset_name)


def _workspace_has_full_profile(workspace: Path) -> bool:
    return all((workspace / kind.filename).is_file() for kind in PROFILE_DOCUMENT_ORDER)


def _workspace_matches_preset(workspace: Path, preset_dir: Path) -> bool:
    """True when workspace IDENTITY matches the preset (same persona already provisioned)."""
    src = preset_dir / "IDENTITY.md"
    dst = workspace / "IDENTITY.md"
    if not src.is_file() or not dst.is_file():
        return False
    try:
        return src.read_text(encoding="utf-8").strip() == dst.read_text(encoding="utf-8").strip()
    except OSError:
        return False


def find_agent_for_preset(preset_name: str, preset_dir: Path) -> OpenClawAgentInfo | None:
    """
    Locate an OpenClaw agent already carrying this preset persona.

    1. Canonical id from preset folder name (franziska for Franziska)
    2. Any agent whose workspace IDENTITY matches the preset
    """
    canonical = preset_canonical_agent_id(preset_name)
    by_id = find_openclaw_agent(canonical)
    if by_id is not None and _workspace_has_full_profile(by_id.workspace):
        return by_id

    for agent in list_openclaw_agents():
        if _workspace_matches_preset(agent.workspace, preset_dir):
            return agent
    return None


def link_skills_for_workspace(workspace: Path) -> tuple[list[str], list[str]]:
    """Symlink bundled/user skills into workspace/skills. Returns (warnings, errors)."""
    result = link_skills_into_workspace(workspace)
    return result.warnings, result.errors


def reuse_agent_with_profile(
    agent: OpenClawAgentInfo,
    profile_dir: Path,
) -> AgentProvisionResult:
    """Sync preset/custom profile into an existing agent workspace (no gateway restart)."""
    sync_errors = sync_profile_to_workspace(profile_dir, agent.workspace)
    skill_result = link_skills_into_workspace(agent.workspace)
    errors = sync_errors + skill_result.errors
    warnings = list(skill_result.warnings)
    if skill_result.linked:
        skill_note = f"已链接 {len(skill_result.linked)} 个 skill: {', '.join(skill_result.linked)}"
    else:
        skill_note = ""
    message = f"已使用已有 Agent: {agent.id}"
    if skill_note:
        message = f"{message} · {skill_note}"
    return AgentProvisionResult(
        ok=not errors,
        agent_id=agent.id,
        workspace=agent.workspace,
        created=False,
        message=message,
        errors=errors,
        warnings=warnings,
    )


def sync_profile_to_workspace(profile_dir: Path, workspace: Path) -> list[str]:
    """
    Copy XHAUS profile docs into the OpenClaw agent workspace (authoritative on disk).

    Preferred for provisioning: OpenClaw reads IDENTITY/SOUL/AGENTS/USER from the
    workspace directory. Gateway `agents.files.set` (see connector mount fallback) is
    for runtime hot-sync when WS + admin scope are available — not required here.
    """
    errors: list[str] = []
    if not profile_dir.is_dir():
        return [f"Profile 目录不存在: {profile_dir}"]

    workspace.mkdir(parents=True, exist_ok=True)
    for kind in PROFILE_DOCUMENT_ORDER:
        src = profile_dir / kind.filename
        dst = workspace / kind.filename
        if not src.is_file():
            errors.append(f"缺少 {kind.filename}")
            continue
        shutil.copy2(src, dst)
    return errors


def configure_deepseek_api_key(agent_id: str, api_key: str) -> tuple[bool, str]:
    """Paste DeepSeek API key into OpenClaw agent auth profiles."""
    key = api_key.strip()
    if not key:
        return False, "API Key 不能为空"

    normalized = normalize_openclaw_agent_id(agent_id)
    try:
        proc = subprocess.run(
            _openclaw_command(
                [
                "models",
                "auth",
                "--agent",
                normalized,
                "paste-api-key",
                "--provider",
                DEEPSEEK_PROVIDER,
                ]
            ),
            input=key + "\n",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"配置 DeepSeek API Key 失败: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "unknown error").strip()
        return False, f"openclaw models auth paste-api-key 失败: {err}"
    return True, "DeepSeek API Key 已写入 OpenClaw"


def restart_openclaw_gateway() -> tuple[bool, str]:
    """Restart Gateway so new agents appear in Dashboard / WS routing."""
    try:
        proc = subprocess.run(
            _openclaw_command(["gateway", "restart"]),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Gateway 重启失败: {exc}"

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "unknown error").strip()
        return False, f"openclaw gateway restart 失败: {err}"
    return True, "Gateway 已重启"


def create_openclaw_agent(
    *,
    display_name: str,
    agent_id: str | None = None,
    workspace: Path | None = None,
    model: str | None = None,
) -> AgentProvisionResult:
    """
    Run `openclaw agents add` (non-interactive) or reuse existing agent by id.
    """
    normalized_id = normalize_openclaw_agent_id(agent_id or display_name)
    existing = find_openclaw_agent(normalized_id)
    if existing:
        return AgentProvisionResult(
            ok=True,
            agent_id=existing.id,
            workspace=existing.workspace,
            created=False,
            message=f"Agent 已存在: {existing.id}",
        )

    ws = (workspace or default_openclaw_workspace(normalized_id)).expanduser()
    model_id = (model or DEFAULT_MODEL).strip()
    # Route/session use normalized_id; add name must normalize to the same id.
    add_name = normalized_id if agent_id else display_name

    try:
        proc = subprocess.run(
            _openclaw_command(
                [
                "agents",
                "add",
                add_name,
                "--workspace",
                str(ws),
                "--model",
                model_id,
                "--non-interactive",
                "--json",
                ]
            ),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return AgentProvisionResult(
            ok=False,
            agent_id=normalized_id,
            errors=[f"无法执行 openclaw agents add: {exc}"],
        )

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "unknown error").strip()
        return AgentProvisionResult(
            ok=False,
            agent_id=normalized_id,
            errors=[f"openclaw agents add 失败: {err}"],
        )

    resolved_id = normalized_id
    try:
        summary = json.loads(proc.stdout)
        if isinstance(summary, dict):
            raw_id = summary.get("id") or summary.get("agentId")
            if isinstance(raw_id, str) and raw_id.strip():
                resolved_id = normalize_openclaw_agent_id(raw_id)
    except json.JSONDecodeError:
        pass

    created = find_openclaw_agent(resolved_id)
    if created is None:
        return AgentProvisionResult(
            ok=False,
            agent_id=normalized_id,
            workspace=ws,
            errors=["Agent 创建后未在列表中找到（可尝试 gateway restart）"],
            warnings=["将尝试重启 Gateway 后再次检测"],
        )

    return AgentProvisionResult(
        ok=True,
        agent_id=created.id,
        workspace=created.workspace,
        created=True,
        message=f"已创建 OpenClaw Agent: {created.id}",
    )


def provision_agent_for_profile(
    *,
    profile_name: str,
    profile_dir: Path,
    mode: str,
    agent_id: str | None = None,
    workspace: Path | None = None,
    model: str | None = None,
    deepseek_api_key: str | None = None,
    restart_gateway: bool = True,
) -> AgentProvisionResult:
    """
    Provision pipeline:
    1. `openclaw agents add <id> --workspace ... --model ...` (or bind existing)
    2. Copy ~/.xhaus/profiles (or preset) docs into agent workspace
    3. Symlink templates/skills + ~/.xhaus/skills → workspace/skills
    4. Optional DeepSeek API key
    5. `openclaw gateway restart`
    """
    warnings: list[str] = []
    normalized_id = normalize_openclaw_agent_id(agent_id or profile_name)
    target_workspace = (workspace or default_openclaw_workspace(normalized_id)).expanduser()

    if mode == "existing":
        if not agent_id:
            return AgentProvisionResult(
                ok=False,
                agent_id="",
                errors=["未选择已有 Agent"],
            )
        found = find_openclaw_agent(agent_id)
        if found is None:
            return AgentProvisionResult(
                ok=False,
                agent_id=normalize_openclaw_agent_id(agent_id),
                errors=[f"未找到 Agent: {agent_id}（可先执行 openclaw gateway restart）"],
            )
        sync_errors = sync_profile_to_workspace(profile_dir, found.workspace)
        skill_result = link_skills_into_workspace(found.workspace)
        bind_errors = sync_errors + skill_result.errors
        bind_warnings = list(skill_result.warnings)
        bind_msg = f"已绑定 Agent: {found.id}"
        if skill_result.linked:
            bind_msg += f" · 已链接 skill: {', '.join(skill_result.linked)}"
        result = AgentProvisionResult(
            ok=not bind_errors,
            agent_id=found.id,
            workspace=found.workspace,
            created=False,
            message=bind_msg,
            errors=bind_errors,
            warnings=bind_warnings,
        )
    else:
        result = create_openclaw_agent(
            display_name=profile_name,
            agent_id=normalized_id,
            workspace=target_workspace,
            model=model or DEFAULT_MODEL,
        )
        if not result.ok:
            return result
        if result.workspace is None:
            return AgentProvisionResult(
                ok=False,
                agent_id=result.agent_id,
                errors=["Agent 工作区未知，无法同步 Profile"],
            )
        sync_errors = sync_profile_to_workspace(profile_dir, result.workspace)
        if sync_errors:
            result.errors.extend(sync_errors)
            result.ok = False
            return result
        skill_result = link_skills_into_workspace(result.workspace)
        result.warnings.extend(skill_result.warnings)
        if skill_result.errors:
            result.errors.extend(skill_result.errors)
            result.ok = False
            return result
        if skill_result.linked:
            note = f"已链接 skill: {', '.join(skill_result.linked)}"
            result.message = f"{result.message} · {note}" if result.message else note

    if deepseek_api_key and mode == "create":
        ok, msg = configure_deepseek_api_key(result.agent_id, deepseek_api_key)
        if ok:
            result.message = f"{result.message} · {msg}" if result.message else msg
        else:
            warnings.append(msg)

    if restart_gateway and (result.created or mode == "create"):
        ok, msg = restart_openclaw_gateway()
        if ok:
            warnings.append(msg)
            refreshed = find_openclaw_agent(result.agent_id)
            if refreshed and refreshed.workspace:
                result.workspace = refreshed.workspace
        else:
            warnings.append(msg)

    result.warnings.extend(warnings)
    return result
