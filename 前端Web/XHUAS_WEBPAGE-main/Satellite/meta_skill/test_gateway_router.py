"""
阶段二验收脚本: 测试 gateway_router.evaluate_habits 能否

  1. 在两份 mock 日志上稳定通过 Pydantic 校验.
  2. 数据 A (重复 "抓网页 + 抽关键词") -> skill_generation.action ∈ {merge, upgrade}.
  3. 数据 B (用户明示 "做视频伪造检测研究, 用学术语气") -> identity_update.action == 'update' 且 patches 非空.
  4. 验证重试机制: 先吐坏 JSON, 再吐合法 JSON, evaluate_habits 仍能成功.

用法
----
    .venv/bin/python test_gateway_router.py            # 离线 mock 模式 (默认)
    .venv/bin/python test_gateway_router.py --live     # 调真 OpenAI (需 OPENAI_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from gateway_router import (
    GatewayDecision,
    LLMClient,
    LLMResponseError,
    OpenAIClient,
    evaluate_habits,
    make_llm_client,
)

logger = logging.getLogger("test_gateway_router")


# --------------------------------------------------------------------------- #
# Mock 日志
# --------------------------------------------------------------------------- #


def _t(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


LOGS_A = json.dumps(
    [
        {
            "timestamp": _t(2),
            "user_intent": "帮我把这篇博客抓下来, 提取关键词",
            "tools_used": [
                {"name": "fetch_url", "args": {"url": "https://blog.example.com/a"}},
                {"name": "extract_keywords", "args": {"text": "<page_a>"}},
            ],
            "assistant_response": "关键词: AI, 安全, 检测",
        },
        {
            "timestamp": _t(26),
            "user_intent": "再抓这一篇, 给我关键词",
            "tools_used": [
                {"name": "fetch_url", "args": {"url": "https://blog.example.com/b"}},
                {"name": "extract_keywords", "args": {"text": "<page_b>"}},
            ],
            "assistant_response": "关键词: 模型, 训练, 推理",
        },
        {
            "timestamp": _t(50),
            "user_intent": "这篇也抓一下并提取关键词",
            "tools_used": [
                {"name": "fetch_url", "args": {"url": "https://news.example.com/c"}},
                {"name": "extract_keywords", "args": {"text": "<page_c>"}},
            ],
            "assistant_response": "关键词: 监管, 风险, 合规",
        },
    ],
    ensure_ascii=False,
    separators=(",", ":"),
)


LOGS_B = json.dumps(
    [
        {
            "timestamp": _t(3),
            "user_intent": (
                "我最近在搞视频伪造检测研究, 你以后回答多用学术语气, "
                "尽量引用最新论文."
            ),
            "tools_used": [],
            "assistant_response": "好的, 后续会以学术语气回答, 并尝试引用最新论文.",
        },
        {
            "timestamp": _t(20),
            "user_intent": "帮我看一下 Deepfake Detection 这个方向最近的 SOTA.",
            "tools_used": [
                {"name": "search_papers", "args": {"q": "deepfake detection 2026"}},
            ],
            "assistant_response": "近期工作主要集中在自监督表征...",
        },
    ],
    ensure_ascii=False,
    separators=(",", ":"),
)


# --------------------------------------------------------------------------- #
# MockLLMClient
# --------------------------------------------------------------------------- #


class MockLLMClient:
    """
    根据 user 消息里的内容启发式生成响应, 模拟一个"听话"的 LLM.
    用于离线验收, 不依赖任何外部服务.
    """

    def __init__(self, *, scripted: list[str] | None = None) -> None:
        # 如果给了脚本就按顺序吐, 否则走启发式分支.
        self._scripted = list(scripted) if scripted else None
        self.calls = 0

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1

        if self._scripted is not None:
            return self._scripted.pop(0)

        # 启发式: 看 user 消息里的关键词
        if "fetch_url" in user and "extract_keywords" in user:
            payload = {
                "skill_generation": {
                    "action": "merge",
                    "target_name": "fetch-and-extract-keywords",
                    "description": (
                        "抓取任意 URL 并自动提取关键词, 一步完成."
                    ),
                    "compile_instruction": (
                        "封装步骤: 1) 调用 fetch_url(url) 拿到正文; "
                        "2) 调用 extract_keywords(text=正文) 拿到关键词数组; "
                        "3) 处理超时与空结果, 失败时返回空列表并打 warning."
                    ),
                },
                "identity_update": {"action": "ignore", "patches": []},
            }
            return json.dumps(payload, ensure_ascii=False)

        if "视频伪造" in user or "学术语气" in user or "deepfake" in user.lower():
            payload = {
                "skill_generation": {
                    "action": "ignore",
                    "target_name": "",
                    "description": "",
                    "compile_instruction": "",
                },
                "identity_update": {
                    "action": "update",
                    "patches": [
                        # 路由示例: 用户事实 -> USER.md; 语气偏好 -> SOUL.md; 方法论 -> AGENTS.md
                        {"target": "USER.md", "content": "用户当前研究方向: 视频伪造检测 (Deepfake Detection)."},
                        {"target": "SOUL.md", "content": "回答风格: 学术语气, 必要时引用近年论文."},
                        {"target": "AGENTS.md", "content": "涉及论文时优先核对最新文献再作答."},
                    ],
                },
            }
            return json.dumps(payload, ensure_ascii=False)

        # 默认 ignore
        return json.dumps(
            {
                "skill_generation": {
                    "action": "ignore",
                    "target_name": "",
                    "description": "",
                    "compile_instruction": "",
                },
                "identity_update": {"action": "ignore", "patches": []},
            },
            ensure_ascii=False,
        )


# 类型自检 (运行时 Protocol 兼容性)
assert isinstance(MockLLMClient(), LLMClient)


# --------------------------------------------------------------------------- #
# 测试用例
# --------------------------------------------------------------------------- #


def _run(name: str, client: LLMClient, logs_json: str) -> GatewayDecision:
    logger.info("--- %s ---", name)
    decision = evaluate_habits(logs_json, client=client, max_retries=3)
    logger.info("decision: %s", decision.model_dump_json(indent=2))
    return decision


def test_case_a(client_factory) -> None:
    decision = _run("CASE A (tool merge)", client_factory(), LOGS_A)
    assert decision.skill_generation.action in ("merge", "upgrade"), (
        f"expected merge/upgrade, got {decision.skill_generation.action!r}"
    )
    assert decision.skill_generation.target_name, "target_name should be non-empty"
    assert decision.skill_generation.compile_instruction, (
        "compile_instruction must guide Skill Compiler"
    )


def test_case_b(client_factory) -> None:
    decision = _run("CASE B (identity update)", client_factory(), LOGS_B)
    iu = decision.identity_update
    assert iu.action == "update", f"expected update, got {iu.action!r}"
    assert iu.patches, "patches must be non-empty"
    # 每条 patch 都带合法 target 路由
    targets = {p.target for p in iu.patches}
    assert targets <= {"IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md"}, targets
    joined = " ".join(p.content for p in iu.patches).lower()
    assert any(k in joined for k in ("视频伪造", "deepfake")), (
        f"patches should mention deepfake topic, got {[p.model_dump() for p in iu.patches]}"
    )


def test_string_patch_backcompat() -> None:
    """纯字符串 patch 应被自动路由到 IDENTITY.md (向后兼容)."""
    good = json.dumps({
        "skill_generation": {"action": "ignore", "target_name": "", "description": "", "compile_instruction": ""},
        "identity_update": {"action": "update", "patches": ["管家自称固定为 Franziska"]},
    })
    client = MockLLMClient(scripted=[good])
    decision = evaluate_habits("[]", client=client, max_retries=1, retry_backoff=0.0)
    iu = decision.identity_update
    assert len(iu.patches) == 1
    assert iu.patches[0].target == "IDENTITY.md"
    assert "Franziska" in iu.patches[0].content


def test_make_llm_client_deepseek() -> None:
    """工厂: provider=deepseek 应指向 api.deepseek.com + deepseek-v4-pro."""
    c = make_llm_client(provider="deepseek", api_key="sk-test", json_mode=True)
    assert c._base_url == "https://api.deepseek.com", c._base_url
    assert c._model == "deepseek-v4-pro", c._model
    assert c._json_mode is True


def test_make_llm_client_env_override() -> None:
    """工厂: env SATELLITE_LLM_* 覆盖 + provider 从 env 读取."""
    saved = {k: os.environ.get(k) for k in
             ("SATELLITE_LLM_PROVIDER", "SATELLITE_LLM_MODEL", "SATELLITE_LLM_API_KEY", "SATELLITE_LLM_BASE_URL")}
    try:
        os.environ["SATELLITE_LLM_PROVIDER"] = "openclaw"
        os.environ["SATELLITE_LLM_API_KEY"] = "tok-123"
        os.environ["SATELLITE_LLM_MODEL"] = "deepseek-v4-flash"
        os.environ.pop("SATELLITE_LLM_BASE_URL", None)
        c = make_llm_client(json_mode=False)
        assert c._base_url == "http://127.0.0.1:18789/v1", c._base_url
        assert c._model == "deepseek-v4-flash", c._model
        assert c._json_mode is False
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_make_llm_client_missing_key() -> None:
    """工厂: 缺 key 时给出明确报错."""
    saved = {k: os.environ.get(k) for k in ("DEEPSEEK_API_KEY", "SATELLITE_LLM_API_KEY", "SATELLITE_LLM_PROVIDER")}
    for k in saved:
        os.environ.pop(k, None)
    raised = False
    try:
        make_llm_client(provider="deepseek")
    except RuntimeError as exc:
        raised = "DEEPSEEK_API_KEY" in str(exc)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    assert raised, "missing key should raise a clear RuntimeError"


def test_retry_recovery() -> None:
    logger.info("--- RETRY (bad JSON -> good JSON) ---")
    good = json.dumps(
        {
            "skill_generation": {
                "action": "ignore",
                "target_name": "",
                "description": "",
                "compile_instruction": "",
            },
            "identity_update": {"action": "ignore", "patches": []},
        }
    )
    client = MockLLMClient(scripted=["this is not json {{{", good])
    decision = evaluate_habits("[]", client=client, max_retries=3, retry_backoff=0.0)
    assert client.calls == 2, f"expected 2 LLM calls, got {client.calls}"
    assert isinstance(decision, GatewayDecision)


def test_retry_exhaustion() -> None:
    logger.info("--- RETRY EXHAUSTION (always bad) ---")
    client = MockLLMClient(scripted=["nope", "still nope", "🙅 still bad"])
    raised = False
    try:
        evaluate_habits("[]", client=client, max_retries=3, retry_backoff=0.0)
    except LLMResponseError as exc:
        raised = True
        assert exc.attempts == 3
        assert exc.last_payload  # 应当保留最后一次原文
    assert raised, "evaluate_habits should raise LLMResponseError on exhaustion"


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call real OpenAI (needs OPENAI_API_KEY). Default uses MockLLMClient.",
    )
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.live:
        def factory() -> LLMClient:
            return OpenAIClient(model=args.model)
    else:
        def factory() -> LLMClient:
            return MockLLMClient()

    failures: list[str] = []
    for name, fn in [
        ("CASE A", lambda: test_case_a(factory)),
        ("CASE B", lambda: test_case_b(factory)),
        ("string patch backcompat", test_string_patch_backcompat),
        ("make_llm_client deepseek", test_make_llm_client_deepseek),
        ("make_llm_client env override", test_make_llm_client_env_override),
        ("make_llm_client missing key", test_make_llm_client_missing_key),
        ("RETRY recovery", test_retry_recovery),
        ("RETRY exhaustion", test_retry_exhaustion),
    ]:
        try:
            fn()
            print(f"[PASS] {name}")
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
            print(f"[FAIL] {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"[ERR ] {name}: {type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(" -", f)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
