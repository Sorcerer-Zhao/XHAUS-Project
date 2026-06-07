"""
阶段三验收脚本: 测试 executor_bridge 的执行层流程.

注意: 需求里写的是 skills/meta_skill/test_executor_bridge.py, 但本项目根目录是
skills/Satellite/ (与 gateway_router / log_sniffer 同级, import 才成立), 故测试置于此.

覆盖点
------
1. Mock 一个 compile_instruction + Mock LLM, 调用 generate_skill_to_staging,
   断言沙盒内整齐生成三件套: SKILL.md / manifest.json / executor.py.
2. 断言生成结果通过原厂 quick_validate (result.valid is True).
3. 断言 LLM 产出的 executor.py 已被正确覆写, 且能通过 py_compile.
4. stage_identity_update: 传入 patches 后生成 identity_patches.json; 空则不落盘.

用法
----
    .venv/bin/python test_executor_bridge.py            # 离线 mock 模式
    .venv/bin/python test_executor_bridge.py --live     # 调真 OpenAI (需 OPENAI_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import logging
import py_compile
import tempfile
from pathlib import Path

from executor_bridge import (
    generate_skill_to_staging,
    stage_identity_update,
)
from gateway_router import LLMClient, OpenAIClient

logger = logging.getLogger("test_executor_bridge")


MOCK_COMPILE_INSTRUCTION = (
    "封装一键流程: 1) fetch_url(url) 抓取网页正文; "
    "2) extract_keywords(text) 提取关键词列表; "
    "3) 处理超时与空结果, 失败返回空列表并打 warning. "
    "对外暴露 run(url: str) -> list[str]."
)

MARKER = "__METASKILL_GENERATED_EXECUTOR__"

MOCK_EXECUTOR_CODE = f'''\
"""fetch-and-extract-keywords executor (mock-generated). {MARKER}"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run(url: str) -> list[str]:
    """抓取 url 正文并提取关键词. 失败返回空列表."""
    if not url:
        logger.warning("empty url")
        return []
    # 占位实现: 真实环境由工具链替换
    return ["ai", "security", "detection"]


if __name__ == "__main__":
    print(run("https://example.com"))
'''


class MockSkillCompilerClient:
    """模拟 Skill Compiler: 不论输入, 返回一段固定的、可编译的 executor 源码."""

    def __init__(self, *, wrap_fence: bool = False) -> None:
        self.calls = 0
        self.wrap_fence = wrap_fence

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        if self.wrap_fence:
            return f"```python\n{MOCK_EXECUTOR_CODE}```"
        return MOCK_EXECUTOR_CODE


assert isinstance(MockSkillCompilerClient(), LLMClient)


BROKEN_CODE = 'def run(:\n    return  # syntax error, missing arg\n'


class MockSelfHealClient:
    """第一次吐坏代码 (语法错误), 第二次 (收到编译错误反馈后) 吐好代码."""

    def __init__(self, *, always_broken: bool = False) -> None:
        self.calls = 0
        self.always_broken = always_broken

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        if self.always_broken:
            return BROKEN_CODE
        return BROKEN_CODE if self.calls == 1 else MOCK_EXECUTOR_CODE


def test_generate_three_files(client_factory, *, wrap_fence: bool) -> None:
    logger.info("--- generate_skill_to_staging (wrap_fence=%s) ---", wrap_fence)
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / ".staging_skills"
        result = generate_skill_to_staging(
            "Fetch And Extract Keywords",  # 故意带空格/大写, 验证归一化
            MOCK_COMPILE_INSTRUCTION,
            client=client_factory(wrap_fence=wrap_fence),
            staging_dir=staging,
        )

        assert result.target_name == "fetch-and-extract-keywords", result.target_name
        assert result.skill_dir == staging / "fetch-and-extract-keywords"

        # 三件套存在
        assert result.skill_md.exists(), "SKILL.md missing"
        assert result.manifest.exists(), "manifest.json missing"
        assert result.executor.exists(), "executor.py missing"
        for name in ("SKILL.md", "manifest.json", "executor.py"):
            assert name in result.files, f"{name} not in {result.files}"

        # 质量关卡: 原厂质检 + 编译检测 双通过
        assert result.valid, f"validation failed: {result.validation_message}"
        assert result.compiled, f"compile failed: {result.compile_message}"
        assert result.passed, "quality gate (valid AND compiled) should pass"

        # executor.py 被正确覆写 (含 marker) 且可编译
        code = result.executor.read_text(encoding="utf-8")
        assert MARKER in code, "executor.py was not overwritten by LLM output"
        assert not code.lstrip().startswith("```"), "code fence not stripped"
        py_compile.compile(str(result.executor), doraise=True)

        # manifest 内容正确
        manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
        assert manifest["name"] == "fetch-and-extract-keywords"
        assert manifest["entrypoint"] == "executor.py"

        logger.info("files generated: %s", result.files)


def test_overwrite_idempotent(client_factory) -> None:
    logger.info("--- overwrite idempotency ---")
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / ".staging_skills"
        for _ in range(2):  # 跑两次, 第二次应清理重建而非报错
            result = generate_skill_to_staging(
                "demo-skill",
                MOCK_COMPILE_INSTRUCTION,
                client=client_factory(wrap_fence=False),
                staging_dir=staging,
            )
        assert result.valid, result.validation_message


def test_compile_self_heal() -> None:
    """首版语法错误 -> 自愈重生一次后编译通过."""
    logger.info("--- compile self-heal ---")
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / ".staging_skills"
        client = MockSelfHealClient()
        result = generate_skill_to_staging(
            "self-heal-demo", MOCK_COMPILE_INSTRUCTION, client=client, staging_dir=staging
        )
        assert client.calls == 2, f"expected 1 retry (2 calls), got {client.calls}"
        assert result.compiled, "should compile after self-heal"
        assert result.passed


def test_compile_gate_fails() -> None:
    """始终语法错误 -> 编译关卡判负 (compiled=False, passed=False)."""
    logger.info("--- compile gate fails ---")
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / ".staging_skills"
        result = generate_skill_to_staging(
            "broken-demo",
            MOCK_COMPILE_INSTRUCTION,
            client=MockSelfHealClient(always_broken=True),
            staging_dir=staging,
        )
        assert not result.compiled, "broken code must fail compile gate"
        assert not result.passed
        assert result.compile_message, "should record compile error message"


def test_stage_identity_update() -> None:
    logger.info("--- stage_identity_update (routed) ---")
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / ".staging_skills"

        # 空 patches -> 不落盘
        assert stage_identity_update([], staging_dir=staging) is None

        # 路由补丁 (字符串默认 IDENTITY.md; dict 指定 target)
        patches = [
            {"target": "USER.md", "content": "用户当前研究方向: 视频伪造检测."},
            {"target": "SOUL.md", "content": "用户偏好学术语气."},
            "管家自称固定为 Franziska",  # 字符串 -> IDENTITY.md
        ]
        path = stage_identity_update(patches, staging_dir=staging)
        assert path is not None and path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert all(set(p) == {"target", "content"} for p in data["patches"]), data["patches"]
        assert set(data["target_files"]) == {"USER.md", "SOUL.md", "IDENTITY.md"}, data["target_files"]

        # 再追加, 去重合并 (USER.md 那条重复, 不应翻倍)
        path2 = stage_identity_update(
            [{"target": "USER.md", "content": "用户当前研究方向: 视频伪造检测."},
             {"target": "AGENTS.md", "content": "先出计划再动手."}],
            staging_dir=staging,
        )
        data2 = json.loads(path2.read_text(encoding="utf-8"))
        assert len(data2["patches"]) == 4, data2["patches"]
        assert "AGENTS.md" in data2["target_files"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.live:
        def factory(*, wrap_fence: bool = False) -> LLMClient:
            return OpenAIClient(model=args.model)
    else:
        def factory(*, wrap_fence: bool = False) -> LLMClient:
            return MockSkillCompilerClient(wrap_fence=wrap_fence)

    checks = [
        ("generate three files", lambda: test_generate_three_files(factory, wrap_fence=False)),
        ("generate w/ code fence", lambda: test_generate_three_files(factory, wrap_fence=True)),
        ("overwrite idempotent", lambda: test_overwrite_idempotent(factory)),
        ("compile self-heal", test_compile_self_heal),
        ("compile gate fails", test_compile_gate_fails),
        ("stage identity update", test_stage_identity_update),
    ]

    failures: list[str] = []
    for name, fn in checks:
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
