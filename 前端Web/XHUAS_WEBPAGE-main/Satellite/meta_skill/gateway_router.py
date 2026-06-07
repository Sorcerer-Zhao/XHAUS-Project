"""
gateway_router.py — MetaSkill 阶段二: 网关层 (策略大脑)

职责
----
吃下阶段一 `log_sniffer.serialize_logs(...)` 产出的紧凑 JSON 数组,
调用大模型做策略研判, 输出严格的 `GatewayDecision`:

  * skill_generation : 是否合并 / 升级 / 忽略, 以及给 Skill Compiler 的编译指令
  * identity_update  : 是否更新身份/认知文件, 以及带文件路由的补丁列表
                       (target ∈ IDENTITY.md / SOUL.md / AGENTS.md / USER.md)

LLM 客户端通过 `LLMClient` Protocol 注入, 默认实现为 `OpenAIClient`
(`response_format={"type":"json_object"}` 强制 JSON 输出).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pydantic Schema
# --------------------------------------------------------------------------- #


class SkillGeneration(BaseModel):
    """技能生成 / 升级决策."""

    action: Literal["merge", "upgrade", "ignore"] = Field(
        ...,
        description=(
            "针对日志里的工具行为采取的动作: "
            "'merge' 表示将多个重复工具调用合并为一个新 Skill; "
            "'upgrade' 表示在已有 Skill 上加新能力; "
            "'ignore' 表示本周期无需生成或升级 Skill."
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
            "action='ignore' 时留空字符串."
        ),
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


# --------------------------------------------------------------------------- #
# System Prompt
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT: str = """\
你是 MetaSkill 的网关层 (Strategy Brain). 你的任务是从过去 3 天的对话日志中
研判用户的行为模式, 并决定是否生成新 Skill 或更新身份预设.

# 输入
- 一个 JSON 数组, 每项 schema:
  {
    "timestamp": "<ISO-8601>",
    "user_intent": "<用户输入>",
    "tools_used": [{"name": "...", "args": {...}, "result": ...}, ...],
    "assistant_response": "<助手回复>"
  }

# 必须分析的三个维度
## (1) 工具行为层 (Tool Behavior)
- 统计相同/相似工具调用序列的出现频次.
- 如果同一组合 (例如 `fetch_url` -> `extract_keywords` -> `summarize`)
  在 ≥2 天里反复出现, 优先考虑 action='merge', 把它封装成一个新 Skill.
- 如果已有 Skill 在日志里出现, 且新场景比原 Skill 多出明显能力, 用 action='upgrade'.
- 命名 target_name 时使用 lowercase + hyphen, 简短且描述性.
- compile_instruction 必须给 Skill Compiler 足够细节:
  * 工具链顺序
  * 输入/输出约定
  * 关键边界条件 (超时, 重试, 空结果...)

## (2) 认知偏好层 (Cognitive Preference)
- 推断用户近期工作主题、兴趣领域、风格偏好.
- 把可固化的事实/偏好作为候选, 例如:
  "用户近期专注于 X 方向研究", "用户偏好 Y 风格的回答".
- 这些信号若清晰且稳定, 体现在 identity_update.patches.

## (3) 显式指令层 (Explicit Instruction) — 最高优先级
- 任何形如 "以后请..." / "从现在开始..." / "记住..." / "下次都..."
  的语句, 都是用户给出的硬性偏好.
- 一旦检测到, 必须把它精炼为一条 patch, 放入 identity_update.patches,
  并将 identity_update.action 设为 'update'. 这条优先级压倒认知层推断.
- 工具行为层的合并请求也可能由显式指令触发
  (例如 "以后帮我把抓网页+提取关键词做成一键自动化"),
  此时同时设置 skill_generation.action='merge' 并写好 compile_instruction.

# 身份/认知补丁的文件路由 (每条 patch 必须带 target)
identity_update.patches 的每一条都要选定 target, 把内容写到最合适的文件:
- "IDENTITY.md" : 管家的人设/名字/对外调性/Vibe (我是谁).
- "SOUL.md"     : 更深的灵魂/价值观/语气与说话方式 (我如何存在与表达).
- "AGENTS.md"   : 工作方法论/操作规则/流程约定 (我该怎么做事; 例如"先出计划再动手").
- "USER.md"     : 关于**主人(用户)本人**的事实与偏好 (用户在做什么研究、喜欢什么、忌讳什么).
路由示例:
- "用户最近在做视频伪造检测研究"            -> target=USER.md
- "以后回答多用学术、严谨的语气"            -> target=SOUL.md (或 IDENTITY.md)
- "以后任何多选构建任务先出计划再动手"      -> target=AGENTS.md
- "把管家的自称固定为 Franziska"            -> target=IDENTITY.md
拿不准时默认 target=IDENTITY.md.

# 重复性检测 (去重) — 生成前必做
- user 消息的 "# 额外上下文" 可能附带一份「现有技能清单」(name/triggers/desc).
- 决定 skill_generation 前, 必须先比对该清单:
  * 若现有某技能已能**完全或更好地覆盖**该需求 -> 用 action='ignore',
    不要重复造轮子 (可在认知层提示用户已有该技能).
  * 若现有技能**接近但缺能力** -> 用 action='upgrade', 且
    target_name 必须设为**那个已存在技能的名字**(而非新名).
  * 只有清单里确实没有可覆盖的技能时, 才用 action='merge' 造新技能.

# 复杂度过滤
- 对"查天气"这类**单步、低复杂度**的偏好, 不要生成 Skill (action='ignore'),
  而是把偏好提炼进 identity_update.patches, 通过身份预设实现.

# 输出格式 — 严格 JSON, 不要任何 Markdown 围栏或前后缀
{
  "skill_generation": {
    "action": "merge" | "upgrade" | "ignore",
    "target_name": "<kebab-case>",
    "description": "<一句话>",
    "compile_instruction": "<给 Skill Compiler 的详细指令>"
  },
  "identity_update": {
    "action": "update" | "ignore",
    "patches": [
      {"target": "USER.md", "content": "<一句话补丁>"},
      {"target": "AGENTS.md", "content": "<一句话补丁>"}
    ]
  }
}

# 规则
- 信号不足时一律使用 action='ignore' 并把相关字段留空.
- 不要编造日志里没有出现的内容.
- 显式指令 > 认知偏好 > 行为统计, 优先级递减.
- 即使两个维度都触发, 也只输出一个 JSON 对象 (二者并列存在).
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
        "model": "deepseek-v4-pro",
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


def _parse_and_validate(payload: str) -> GatewayDecision:
    try:
        data = json.loads(_strip_json_fence(payload))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error: {exc.msg} (line {exc.lineno})") from exc
    return GatewayDecision.model_validate(data)


def evaluate_habits(
    logs_json: str,
    *,
    client: LLMClient | None = None,
    max_retries: int = 3,
    retry_backoff: float = 1.0,
    extra_user_context: str = "",
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

    异常
    ----
    LLMResponseError
        重试用尽仍未通过 Schema 校验.
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    if client is None:
        client = OpenAIClient()

    base_user = (
        "以下是过去 3 天的对话日志 (紧凑 JSON 数组). "
        "请按系统提示完成研判并仅返回 JSON 对象.\n\n"
        f"<LOGS_JSON>\n{logs_json}\n</LOGS_JSON>"
    )
    if extra_user_context:
        base_user += f"\n\n# 额外上下文\n{extra_user_context}"

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
            err = f"LLM call raised {type(exc).__name__}: {exc}"
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

        logger.info("evaluate_habits succeeded on attempt %d", attempt)
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
