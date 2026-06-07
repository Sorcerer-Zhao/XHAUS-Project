"""
gateway_router.py — MetaSkill 阶段二: 网关层 (策略大脑)

职责
----
吃下阶段一 `log_sniffer.serialize_logs(...)` 产出的紧凑 JSON 数组,
调用大模型做策略研判, 输出严格的 `GatewayDecision`:

  * skill_opportunity : Skill 机会挖掘 (reuse / tool_chain / proposal / do_nothing)
  * skill_generation  : 是否合并 / 升级 / 建议 / 忽略, 以及编译指令与匹配信息
  * identity_update   : 是否更新身份/认知文件, 以及带文件路由的补丁列表
                        (target ∈ IDENTITY.md / SOUL.md / AGENTS.md / USER.md)

LLM 客户端通过 `LLMClient` Protocol 注入, 默认实现为 `OpenAIClient`
(`response_format={"type":"json_object"}` 强制 JSON 输出).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pydantic Schema
# --------------------------------------------------------------------------- #


SkillOpportunityKind = Literal[
    "reuse_existing_skill",
    "tool_chain_composition",
    "new_skill_proposal",
    "do_nothing",
]


class NewSkillSpec(BaseModel):
    """最小化新 Skill 提案 (不直接进入执行层时使用)."""

    name: str = Field(default="", description="提议的 kebab-case 技能名.")
    description: str = Field(default="", description="一句话描述.")
    proposed_triggers: list[str] = Field(default_factory=list)
    tool_chain: list[str] = Field(default_factory=list)
    rationale: str = Field(default="", description="为何值得做成 Skill.")


class SkillOpportunityDecision(BaseModel):
    """Skill 机会挖掘的结构化决策 (网关核心中间态)."""

    decision: SkillOpportunityKind = Field(
        default="do_nothing",
        description=(
            "reuse_existing_skill: 已有 Skill 可覆盖, 不新建; "
            "tool_chain_composition: 重复稳定工具链, 值得封装复合 Skill; "
            "new_skill_proposal: 有苗头但只输出最小提案, 不进执行层; "
            "do_nothing: 本周期无 Skill 机会."
        ),
    )
    matched_skills: list[str] = Field(
        default_factory=list,
        description="已存在且可复用/可升级的 Skill 名列表.",
    )
    missing_capabilities: list[str] = Field(
        default_factory=list,
        description="现有 Skill 未覆盖的能力缺口 (API/工具链/场景).",
    )
    tool_chain_signature: str = Field(
        default="",
        description="重复出现的工具链签名, 如 fetch_url->extract_keywords.",
    )
    new_skill_spec: NewSkillSpec | None = Field(
        default=None,
        description="new_skill_proposal / tool_chain_composition 时的结构化草案.",
    )
    decision_reason: str = Field(
        default="",
        description="结构化决策理由 (短句, 供日志与 HIL 展示).",
    )


class SkillGeneration(BaseModel):
    """技能生成 / 升级决策 (与 skill_opportunity 联动, 保留旧字段兼容)."""

    action: Literal["merge", "upgrade", "suggest", "ignore"] = Field(
        ...,
        description=(
            "针对日志里的工具行为采取的动作: "
            "'merge' 表示高度置信，将多个重复工具调用合并为一个新 Skill; "
            "'upgrade' 表示高度置信，在已有 Skill 上加新能力; "
            "'suggest' 表示中等置信度——模式出现了但把握不够，输出草稿供用户审视; "
            "'ignore' 表示本周期完全无信号，无需任何动作."
        ),
    )
    target_name: str = Field(
        default="",
        description=(
            "目标 Skill 名 (lowercase / hyphen). "
            "action='ignore' 时留空字符串."
        ),
    )
    description: str = Field(
        default="",
        description="该 Skill 的一句话描述, 用于 SKILL.md 的 frontmatter.",
    )
    compile_instruction: str = Field(
        default="",
        description=(
            "给执行层 Skill Compiler 的详细编译指令, 包括: "
            "需要封装的工具调用序列、入参/出参约定、关键边界条件等. "
            "action='ignore' / new_skill_proposal 时留空或极简."
        ),
    )
    matched_skills: list[str] = Field(
        default_factory=list,
        description="与机会层一致的已匹配 Skill 名.",
    )
    missing_capabilities: list[str] = Field(
        default_factory=list,
        description="与机会层一致的能力缺口.",
    )
    new_skill_spec: NewSkillSpec | None = Field(
        default=None,
        description="结构化 Skill 草案 (提案或复合 Skill 规格).",
    )

    @field_validator("target_name")
    @classmethod
    def _check_name(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        if info.data.get("action") in ("merge", "upgrade") and not v.strip():
            raise ValueError(
                "target_name is required when action is 'merge' or 'upgrade'."
            )
        return v.strip()


# 允许被更新的身份/认知文件 (均位于工作区根, 与 skills/ 同级)
TargetFile = Literal["IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md"]
TARGET_FILES: tuple[str, ...] = ("IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md")


class FilePatch(BaseModel):
    """一条带目标文件路由的认知补丁."""

    target: TargetFile = Field(
        default="IDENTITY.md",
        description=(
            "该补丁应并入哪个文件: "
            "IDENTITY.md(人设/名字/调性) | SOUL.md(灵魂/价值观/语气) | "
            "AGENTS.md(工作方法/规则/约定) | USER.md(关于主人的事实与偏好)."
        ),
    )
    content: str = Field(..., description="补丁正文 (自然语言, 一句话).")

    @field_validator("content")
    @classmethod
    def _strip_content(cls, v: str) -> str:
        return v.strip()


class IdentityUpdate(BaseModel):
    """身份/认知文件 (IDENTITY/SOUL/AGENTS/USER) 更新决策, 支持按文件路由."""

    action: Literal["update", "ignore"] = Field(
        ...,
        description=(
            "'update' 表示需要向某个身份/认知文件追加补丁; "
            "'ignore' 表示日志中没有足以触发更新的信号."
        ),
    )
    patches: list[FilePatch] = Field(
        default_factory=list,
        description=(
            "若干条带 target 路由的补丁. 每项 {target, content}. "
            "action='ignore' 时为空列表. (兼容: 纯字符串视为 target=IDENTITY.md)"
        ),
    )

    @field_validator("patches", mode="before")
    @classmethod
    def _coerce_patches(cls, v):  # type: ignore[no-untyped-def]
        """兼容三种写法: 纯字符串 / {target,content} / FilePatch."""
        if not v:
            return []
        out: list[Any] = []
        for item in v:
            if isinstance(item, str):
                if item.strip():
                    out.append({"target": "IDENTITY.md", "content": item})
            else:
                out.append(item)
        return out

    @field_validator("patches")
    @classmethod
    def _check_patches(cls, v: list[FilePatch], info) -> list[FilePatch]:  # type: ignore[no-untyped-def]
        kept = [p for p in v if p.content.strip()]
        if info.data.get("action") == "update" and not kept:
            raise ValueError("patches must be non-empty when action is 'update'.")
        return kept


class GatewayDecision(BaseModel):
    """阶段二最终产出."""

    skill_generation: SkillGeneration
    identity_update: IdentityUpdate
    skill_opportunity: SkillOpportunityDecision | None = Field(
        default=None,
        description="Skill 机会挖掘层; 缺省时由 reconcile 从 skill_generation 推断.",
    )


# --------------------------------------------------------------------------- #
# System Prompt
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT: str = """\
你是 MetaSkill 的网关层 (Strategy Brain) — 结构化决策器, 不是散文总结器.
你的任务: 从日志 + 召回记忆 + 能力快照中, 输出严格 JSON 决策.

# 输入 (user 消息可能包含多段)
- <LOGS_JSON> 过去窗口的紧凑对话数组
- <RETRIEVED_MEMORY> 高相关记忆 chunk (优先于通读全量日志)
- <TRAIT_MEMORY> 用户特质/偏好记忆
- <CAPABILITY_SNAPSHOT> workspace 能力快照 (API keys / skills / gaps)
- # 额外上下文: 现有技能清单等

# 判断优先级 (严格顺序, 后者不得压过前者)
0. **显式指令** (最高): "以后请…" / "记住…" / "固定成技能…"
1. **能力缺口**: TOOLS.md 有 key 但 skills/ 无对应 Skill
2. **重复工具链**: 同一 tool 序列多次出现
3. **工具链稳定性**: 序列一致、参数形态稳定
4. **认知偏好** (最低): 工作主题/语气/习惯 → 主要进 identity_update

# 两段式 Skill 机会判断 (必须先做 skill_opportunity, 再填 skill_generation)

## 阶段 A — 是否已有 Skill 可覆盖? (reuse vs gap)
对照 CAPABILITY_SNAPSHOT / 技能清单 / matched_skills:
- 若**完全覆盖** → skill_opportunity.decision = "reuse_existing_skill"
  * matched_skills 填已有技能名
  * skill_generation.action = "ignore"
  * **不要**新建 Skill
- 若**接近但缺能力** → missing_capabilities 列缺口; 考虑 upgrade 或 new_skill_proposal
- 若**能力缺口明显** (有 API 无 Skill) → missing_capabilities 必填; 倾向 new_skill_proposal

## 阶段 B — 是否值得把重复工具链合成新 Skill?
仅当阶段 A 未判定 reuse_existing_skill 时进行:
- 同一 tool_chain_signature (如 fetch_url->extract_keywords) **稳定重复** (≥3 次或跨天)
  → skill_opportunity.decision = "tool_chain_composition"
  → skill_generation.action = "merge" (高置信) 或 "upgrade" (扩展现有)
  → compile_instruction 写清工具链/入参/出参/边界
- 有苗头但证据不足 (约 2 次 / 不稳定)
  → skill_opportunity.decision = "new_skill_proposal"
  → skill_generation.action = "suggest"
  → **compile_instruction 留空**; 只填 new_skill_spec (最小提案)
- 无信号 → skill_opportunity.decision = "do_nothing"; skill_generation.action = "ignore"

# skill_opportunity.decision 与 skill_generation.action 对齐
| opportunity.decision      | generation.action | compile_instruction |
|---------------------------|-------------------|---------------------|
| reuse_existing_skill      | ignore            | 空                  |
| tool_chain_composition    | merge / upgrade   | 完整详细            |
| new_skill_proposal        | suggest           | 空 (仅 new_skill_spec) |
| do_nothing                | ignore            | 空                  |

# 身份补丁路由 (identity_update.patches 每项带 target)
IDENTITY.md / SOUL.md / AGENTS.md / USER.md — 显式指令优先写入 patches.

# 复杂度过滤
单步低复杂度偏好 (如查天气) → 不造 Skill, 写入 identity_update.

# 输出 — 严格 JSON, 无 Markdown 围栏
{
  "skill_opportunity": {
    "decision": "reuse_existing_skill|tool_chain_composition|new_skill_proposal|do_nothing",
    "matched_skills": ["<existing-skill>"],
    "missing_capabilities": ["<gap>"],
    "tool_chain_signature": "<tool_a->tool_b>",
    "new_skill_spec": {
      "name": "<kebab-case>",
      "description": "<一句话>",
      "proposed_triggers": ["<触发词>"],
      "tool_chain": ["fetch_url", "extract_keywords"],
      "rationale": "<为何值得>"
    },
    "decision_reason": "<结构化理由>"
  },
  "skill_generation": {
    "action": "merge|upgrade|suggest|ignore",
    "target_name": "<kebab-case>",
    "description": "<一句话>",
    "compile_instruction": "<仅 merge/upgrade 时详细; proposal 时留空>",
    "matched_skills": [],
    "missing_capabilities": [],
    "new_skill_spec": { "...同上, 可复用..." }
  },
  "identity_update": {
    "action": "update|ignore",
    "patches": [{"target": "USER.md", "content": "..."}]
  }
}

# 硬性规则
- 不要编造日志/快照中不存在的内容.
- reuse_existing_skill 时 decision_reason 必须说明复用哪个 Skill.
- new_skill_proposal 时**禁止**写长 compile_instruction.
- tool_chain_composition 时 tool_chain_signature 非空且 new_skill_spec.tool_chain 对齐.
- 只输出一个 JSON 对象.
"""


# --------------------------------------------------------------------------- #
# LLM Client 协议 + 默认实现
# --------------------------------------------------------------------------- #


@runtime_checkable
class LLMClient(Protocol):
    """最小化的 chat completion 接口, 便于注入 mock."""

    def complete(self, *, system: str, user: str) -> str: ...


class OpenAIClient:
    """
    OpenAI 兼容客户端 (chat.completions). 通过 base_url 可指向任何
    OpenAI-completions 兼容服务: OpenAI / DeepSeek / OpenClaw 网关 等.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        timeout: float = 60.0,
        json_mode: bool = True,
    ) -> None:
        try:
            from openai import OpenAI  # 延迟导入, 让单测可以跑 mock 模式
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "openai SDK is not installed. `pip install openai` or inject a mock."
            ) from exc

        self._OpenAI = OpenAI
        self._model = model
        self._temperature = temperature
        self._timeout = timeout
        # json_mode=True 强制 JSON 输出 (策略研判); False 用于代码/Markdown 生成.
        self._json_mode = json_mode
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL") or None
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "API key is not set. "
                "Export OPENAI_API_KEY (or pass api_key=), "
                "或使用 make_llm_client() 走 DeepSeek/OpenClaw 配置."
            )
        client_kwargs: dict[str, Any] = {"api_key": self._api_key, "timeout": self._timeout}
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        self._client = self._OpenAI(**client_kwargs)

    def complete(self, *, system: str, user: str) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        return content


# --------------------------------------------------------------------------- #
# 客户端工厂: 一处配置, 支持 DeepSeek / OpenClaw 网关 / OpenAI
# --------------------------------------------------------------------------- #

# Provider 预设: base_url + 默认模型 + 取 key 的环境变量名
_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    # OpenClaw 配置的 DeepSeek 是 openai-completions 兼容 (baseUrl=api.deepseek.com)
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "key_env": "DEEPSEEK_API_KEY",
    },
    # 直连 OpenClaw 本地网关暴露的 OpenAI 兼容 chatCompletions 端点
    "openclaw": {
        "base_url": "http://127.0.0.1:18789/v1",
        "model": "openclaw",
        "key_env": "OPENCLAW_GATEWAY_TOKEN",
    },
    "openai": {
        "base_url": "",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
}


def make_llm_client(
    *,
    json_mode: bool = True,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> "OpenAIClient":
    """
    按环境/参数构造合适的 LLM 客户端.

    provider 取值 (默认读 env SATELLITE_LLM_PROVIDER, 再默认 'deepseek'):
      - "deepseek" : 直连 DeepSeek (api.deepseek.com), 默认模型 deepseek-v4-pro,
                     key 取 env DEEPSEEK_API_KEY.
      - "openclaw" : 直连本地 OpenClaw 网关 OpenAI 兼容端点 (:18789/v1),
                     key 取 env OPENCLAW_GATEWAY_TOKEN.
      - "openai"   : 标准 OpenAI, key 取 env OPENAI_API_KEY.
    任意字段都可被显式参数或对应 env 覆盖:
      SATELLITE_LLM_MODEL / SATELLITE_LLM_BASE_URL / SATELLITE_LLM_API_KEY.
    """
    provider = (provider or os.environ.get("SATELLITE_LLM_PROVIDER") or "deepseek").lower()
    preset = _PROVIDER_PRESETS.get(provider, _PROVIDER_PRESETS["deepseek"])

    resolved_model = (
        model or os.environ.get("SATELLITE_LLM_MODEL") or preset["model"]
    )
    resolved_base = (
        base_url
        or os.environ.get("SATELLITE_LLM_BASE_URL")
        or (preset["base_url"] or None)
    )
    resolved_key = (
        api_key
        or os.environ.get("SATELLITE_LLM_API_KEY")
        or os.environ.get(preset["key_env"])
    )
    if not resolved_key:
        raise RuntimeError(
            f"未找到 {provider} 的 API key. 请设置 env {preset['key_env']} "
            f"(或 SATELLITE_LLM_API_KEY), 见 README『接入 DeepSeek / OpenClaw』."
        )
    logger.info(
        "make_llm_client provider=%s model=%s base_url=%s json_mode=%s",
        provider, resolved_model, resolved_base or "(default)", json_mode,
    )
    return OpenAIClient(
        model=resolved_model,
        api_key=resolved_key,
        base_url=resolved_base,
        json_mode=json_mode,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class GatewayRouterError(Exception):
    """gateway_router 顶层异常."""


class LLMResponseError(GatewayRouterError):
    """LLM 多轮重试后仍未能产出合法 JSON / 通过 Schema 校验."""

    def __init__(self, message: str, last_payload: str = "", attempts: int = 0) -> None:
        super().__init__(message)
        self.last_payload = last_payload
        self.attempts = attempts


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


@dataclass
class _Attempt:
    raw: str
    error: str


def _strip_json_fence(text: str) -> str:
    """部分模型即使要求 JSON mode 也会偷偷加 ```json 围栏, 这里兜底."""
    t = text.strip()
    if t.startswith("```"):
        # 去掉第一行围栏
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
    return t.strip()


def _context_blob(
    value: str | dict[str, Any] | list[Any] | None,
    *,
    empty_label: str = "[]",
) -> str:
    """把各类上下文输入规整为嵌入 user 消息的 JSON 字符串."""
    if value is None:
        return empty_label
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or empty_label
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _chain_signature(tool_chain: Sequence[str]) -> str:
    return "->".join(t for t in tool_chain if t)


def _composite_compile_draft(spec: NewSkillSpec, signature: str) -> str:
    """tool_chain_composition 时, 若 LLM 未写 compile_instruction, 由 Python 层生成复合草案."""
    chain = " -> ".join(spec.tool_chain) if spec.tool_chain else signature.replace("->", " -> ")
    triggers = ", ".join(spec.proposed_triggers) if spec.proposed_triggers else "(infer from logs)"
    return (
        f"Composite skill '{spec.name}': {spec.description}\n"
        f"Tool chain: {chain}\n"
        f"Suggested triggers: {triggers}\n"
        f"Rationale: {spec.rationale}\n"
        "Wrap the chain as a single callable entry; handle timeouts, empty results, and retries."
    )


def infer_default_skill_opportunity(sg: SkillGeneration) -> SkillOpportunityDecision:
    """旧版 LLM 未返回 skill_opportunity 时, 从 skill_generation 反向推断."""
    if sg.action == "ignore":
        return SkillOpportunityDecision(
            decision="do_nothing",
            matched_skills=list(sg.matched_skills),
            missing_capabilities=list(sg.missing_capabilities),
            decision_reason="inferred from skill_generation.action=ignore",
        )
    if sg.action in ("merge", "upgrade"):
        spec = sg.new_skill_spec
        chain = spec.tool_chain if spec else []
        return SkillOpportunityDecision(
            decision="tool_chain_composition",
            matched_skills=list(sg.matched_skills),
            missing_capabilities=list(sg.missing_capabilities),
            tool_chain_signature=_chain_signature(chain),
            new_skill_spec=spec,
            decision_reason=f"inferred from skill_generation.action={sg.action}",
        )
    if sg.action == "suggest":
        return SkillOpportunityDecision(
            decision="new_skill_proposal",
            matched_skills=list(sg.matched_skills),
            missing_capabilities=list(sg.missing_capabilities),
            new_skill_spec=sg.new_skill_spec,
            decision_reason="inferred from skill_generation.action=suggest",
        )
    return SkillOpportunityDecision(decision="do_nothing")


def _sync_opportunity_layers(
    sg: SkillGeneration,
    opp: SkillOpportunityDecision,
) -> tuple[SkillGeneration, SkillOpportunityDecision]:
    """合并两层共有的 matched / missing / spec 字段."""
    matched = opp.matched_skills or sg.matched_skills
    missing = opp.missing_capabilities or sg.missing_capabilities
    spec = opp.new_skill_spec or sg.new_skill_spec
    opp = opp.model_copy(
        update={
            "matched_skills": matched,
            "missing_capabilities": missing,
            "new_skill_spec": spec,
        }
    )
    sg = sg.model_copy(
        update={
            "matched_skills": matched,
            "missing_capabilities": missing,
            "new_skill_spec": spec,
        }
    )
    return sg, opp


def _resolve_layer_conflict(
    sg: SkillGeneration,
    opp: SkillOpportunityDecision,
) -> SkillOpportunityDecision:
    """当 opportunity 与 generation 不一致时, 按 generation 的显式动作上调机会层."""
    if opp.decision != "do_nothing":
        return opp
    if sg.action in ("merge", "upgrade"):
        spec = sg.new_skill_spec
        chain = spec.tool_chain if spec else []
        return opp.model_copy(
            update={
                "decision": "tool_chain_composition",
                "tool_chain_signature": opp.tool_chain_signature or _chain_signature(chain),
                "decision_reason": opp.decision_reason
                or f"reconciled: generation.action={sg.action}",
            }
        )
    if sg.action == "suggest":
        return opp.model_copy(
            update={
                "decision": "new_skill_proposal",
                "decision_reason": opp.decision_reason
                or "reconciled: generation.action=suggest",
            }
        )
    return opp


def reconcile_gateway_decision(decision: GatewayDecision) -> GatewayDecision:
    """
    结构化后处理: 同步 skill_opportunity 与 skill_generation,
    强制执行中间态语义 (proposal 不写 compile_instruction, composition 优先生成草案).
    """
    sg = decision.skill_generation
    opp = decision.skill_opportunity or infer_default_skill_opportunity(sg)
    opp = _resolve_layer_conflict(sg, opp)
    sg, opp = _sync_opportunity_layers(sg, opp)

    kind = opp.decision

    if kind == "reuse_existing_skill":
        sg = sg.model_copy(
            update={
                "action": "ignore",
                "target_name": "",
                "compile_instruction": "",
                "description": sg.description
                or (
                    f"Reuse: {', '.join(opp.matched_skills)}"
                    if opp.matched_skills
                    else ""
                ),
            }
        )
    elif kind == "new_skill_proposal":
        spec = opp.new_skill_spec
        target = sg.target_name or (spec.name if spec else "")
        desc = sg.description or (spec.description if spec else "")
        sg = sg.model_copy(
            update={
                "action": "suggest",
                "target_name": target,
                "description": desc,
                "compile_instruction": "",
                "new_skill_spec": spec,
            }
        )
        if spec and not opp.tool_chain_signature and spec.tool_chain:
            opp = opp.model_copy(
                update={"tool_chain_signature": _chain_signature(spec.tool_chain)}
            )
    elif kind == "tool_chain_composition":
        spec = opp.new_skill_spec
        target = sg.target_name or (spec.name if spec else "")
        desc = sg.description or (spec.description if spec else "")
        compile_inst = sg.compile_instruction.strip()
        if not compile_inst and spec and spec.name:
            compile_inst = _composite_compile_draft(spec, opp.tool_chain_signature)
        action = sg.action if sg.action in ("merge", "upgrade") else "merge"
        sg = sg.model_copy(
            update={
                "action": action,
                "target_name": target,
                "description": desc,
                "compile_instruction": compile_inst,
                "new_skill_spec": spec,
            }
        )
        if not opp.tool_chain_signature and spec and spec.tool_chain:
            opp = opp.model_copy(
                update={"tool_chain_signature": _chain_signature(spec.tool_chain)}
            )
    elif kind == "do_nothing" and sg.action == "ignore":
        sg = sg.model_copy(update={"compile_instruction": ""})

    if kind == "new_skill_proposal" and sg.compile_instruction.strip():
        sg = sg.model_copy(update={"compile_instruction": ""})

    return GatewayDecision(
        skill_generation=sg,
        identity_update=decision.identity_update,
        skill_opportunity=opp,
    )


def is_skill_execution_ready(decision: GatewayDecision) -> bool:
    """
    是否应进入 Skill Compiler 执行层.
    new_skill_proposal / reuse_existing_skill / do_nothing 均返回 False.
    """
    sg = decision.skill_generation
    opp = decision.skill_opportunity

    if opp is None:
        return sg.action in ("merge", "upgrade") and bool(sg.compile_instruction.strip())

    if opp.decision != "tool_chain_composition":
        return False
    return sg.action in ("merge", "upgrade") and bool(sg.compile_instruction.strip())


def _parse_and_validate(payload: str) -> GatewayDecision:
    try:
        data = json.loads(_strip_json_fence(payload))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error: {exc.msg} (line {exc.lineno})") from exc
    decision = GatewayDecision.model_validate(data)
    return reconcile_gateway_decision(decision)


def _build_user_message(
    logs_json: str,
    *,
    retrieved_memory: str | dict[str, Any] | list[Any] | None = None,
    trait_memory: str | dict[str, Any] | list[Any] | None = None,
    capability_snapshot: str | dict[str, Any] | None = None,
    extra_user_context: str = "",
) -> str:
    """组装多段结构化上下文, 供两段式 Skill 机会判断消费."""
    parts = [
        "请按系统提示完成两段式 Skill 机会判断, 并仅返回 JSON 对象.",
        f"<LOGS_JSON>\n{logs_json}\n</LOGS_JSON>",
        f"<RETRIEVED_MEMORY>\n{_context_blob(retrieved_memory)}\n</RETRIEVED_MEMORY>",
        f"<TRAIT_MEMORY>\n{_context_blob(trait_memory)}\n</TRAIT_MEMORY>",
        f"<CAPABILITY_SNAPSHOT>\n{_context_blob(capability_snapshot, empty_label='{}')}\n</CAPABILITY_SNAPSHOT>",
    ]
    msg = "\n\n".join(parts).replace("\u2026", "...")
    if extra_user_context.strip():
        msg += f"\n\n# 额外上下文\n{extra_user_context.strip()}"
    return msg


def evaluate_habits(
    logs_json: str,
    *,
    client: LLMClient | None = None,
    max_retries: int = 3,
    retry_backoff: float = 1.0,
    extra_user_context: str = "",
    retrieved_memory: str | dict[str, Any] | list[Any] | None = None,
    trait_memory: str | dict[str, Any] | list[Any] | None = None,
    capability_snapshot: str | dict[str, Any] | None = None,
) -> GatewayDecision:
    """
    调用 LLM 研判最近的日志, 返回严格校验过的 `GatewayDecision`.

    参数
    ----
    logs_json: str
        阶段一 `serialize_logs(...)` 的紧凑 JSON 数组字符串.
    client: LLMClient | None
        LLM 客户端, 默认创建 `OpenAIClient`. 测试可注入 mock.
    max_retries: int
        总尝试次数 (含首次), 必须 >= 1.
    retry_backoff: float
        失败后基础休眠秒数, 每次重试线性递增.
    extra_user_context: str
        追加在 user 消息末尾的可选上下文 (例如已有 Skill 清单).
    retrieved_memory: str | list | None
        高相关记忆 chunk (JSON 字符串或序列), 来自 log_sniffer.retrieve.
    trait_memory: str | list | None
        用户特质/显式偏好记忆 (JSON 字符串或序列).
    capability_snapshot: str | dict | None
        workspace 能力快照, 来自 log_sniffer.CapabilitySnapshot.

    异常
    ----
    LLMResponseError
        重试用尽仍未通过 Schema 校验.
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    if client is None:
        client = OpenAIClient()

    base_user = _build_user_message(
        logs_json,
        retrieved_memory=retrieved_memory,
        trait_memory=trait_memory,
        capability_snapshot=capability_snapshot,
        extra_user_context=extra_user_context,
    )

    history: list[_Attempt] = []
    last_payload = ""

    for attempt in range(1, max_retries + 1):
        if history:
            # 把上一次的错误反馈给模型, 引导其修正
            prev = history[-1]
            user = (
                base_user
                + "\n\n# 你上一次的回复未通过校验, 请修正后重新输出 JSON.\n"
                + f"## 上次回复\n{prev.raw}\n\n## 错误\n{prev.error}\n"
                + "请严格按 System Prompt 的 JSON Schema 输出, 不要任何额外文字."
            )
        else:
            user = base_user

        logger.info("evaluate_habits attempt %d/%d", attempt, max_retries)
        try:
            raw = client.complete(system=SYSTEM_PROMPT, user=user)
        except Exception as exc:  # noqa: BLE001 — 网络/SDK 异常一律重试
            err = f"LLM call raised {type(exc).__name__}: {ascii(str(exc))[:200]}"
            logger.warning("%s", err)
            history.append(_Attempt(raw="", error=err))
            time.sleep(retry_backoff * attempt)
            continue

        last_payload = raw
        try:
            decision = _parse_and_validate(raw)
        except (ValueError, ValidationError) as exc:
            err = (
                exc.errors() if isinstance(exc, ValidationError) else str(exc)
            )  # type: ignore[assignment]
            err_text = json.dumps(err, ensure_ascii=False) if not isinstance(err, str) else err
            logger.warning("Validation failed on attempt %d: %s", attempt, err_text)
            history.append(_Attempt(raw=raw, error=err_text))
            time.sleep(retry_backoff * attempt)
            continue

        logger.info(
            "evaluate_habits succeeded on attempt %d (opportunity=%s, skill=%s)",
            attempt,
            decision.skill_opportunity.decision if decision.skill_opportunity else None,
            decision.skill_generation.action,
        )
        return decision

    raise LLMResponseError(
        f"LLM failed to produce a valid GatewayDecision after {max_retries} attempts.",
        last_payload=last_payload,
        attempts=max_retries,
    )


# --------------------------------------------------------------------------- #
# CLI: gateway_router.py <logs.json>
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(description="MetaSkill Phase 2 — Gateway router.")
    p.add_argument("logs", help="Path to a JSON file produced by log_sniffer.")
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    with open(args.logs, encoding="utf-8") as f:
        logs_json = f.read().strip()

    try:
        decision = evaluate_habits(
            logs_json,
            client=OpenAIClient(model=args.model),
            max_retries=args.retries,
        )
    except LLMResponseError as exc:
        logger.error("Gateway failed: %s", exc)
        sys.stderr.write(f"--- last LLM payload ---\n{exc.last_payload}\n")
        return 1

    sys.stdout.write(decision.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
