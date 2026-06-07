"""
main_satellite 全流程测试 (离线 mock): markdown 源 + 去重清单 +
身份/认知文件按 target 路由合并 (IDENTITY/SOUL/AGENTS/USER) + 技能挂载.

    .venv/bin/python test_main_satellite.py
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import main_satellite as ms
from main_satellite import _apply_identity_updates, _dedup_append

logger = logging.getLogger("test_main_satellite")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class MockGatewayMerge:
    """返回 merge 决策 + 路由到多个文件的 identity update. 记录去重清单上下文."""

    def __init__(self) -> None:
        self.last_user = ""

    def complete(self, *, system: str, user: str) -> str:
        self.last_user = user
        return json.dumps({
            "skill_opportunity": {
                "decision": "tool_chain_composition",
                "matched_skills": [],
                "missing_capabilities": [],
                "tool_chain_signature": "fetch_url->extract_keywords",
                "new_skill_spec": {
                    "name": "web-keyword-extractor",
                    "description": "抓网页并提取关键词",
                    "proposed_triggers": ["抓网页"],
                    "tool_chain": ["fetch_url", "extract_keywords"],
                    "rationale": "repeated tool chain in logs",
                },
                "decision_reason": "stable repeated chain",
            },
            "skill_generation": {
                "action": "merge",
                "target_name": "web-keyword-extractor",
                "description": "抓网页并提取关键词",
                "compile_instruction": "封装 fetch_url -> extract_keywords，暴露 run(url)。",
            },
            "identity_update": {
                "action": "update",
                "patches": [
                    {"target": "USER.md", "content": "用户近期在做网页信息抽取"},
                    {"target": "SOUL.md", "content": "偏好简短直接的回答"},
                    {"target": "IDENTITY.md", "content": "自称 Franziska"},
                ],
            },
        }, ensure_ascii=False)


class MockGatewayIgnore:
    def complete(self, *, system: str, user: str) -> str:
        return json.dumps({
            "skill_opportunity": {
                "decision": "do_nothing",
                "matched_skills": [],
                "missing_capabilities": [],
                "tool_chain_signature": "",
                "decision_reason": "none",
            },
            "skill_generation": {"action": "ignore", "target_name": "", "description": "", "compile_instruction": ""},
            "identity_update": {"action": "ignore", "patches": []},
        })


class MockForge:
    def complete(self, *, system: str, user: str) -> str:
        return '"""generated"""\n\n\ndef run(url: str) -> list[str]:\n    return []\n'


class MockFileMerger:
    """模拟文本模式 LLM: 回显既有内容 + 待并入补丁 (并记录被处理的文件名)."""

    def __init__(self) -> None:
        self.files_seen: list[str] = []

    def complete(self, *, system: str, user: str) -> str:
        m = re.search(r"维护一个 AI 管家的文件 (\S+)", system)
        self.files_seen.append(m.group(1) if m else "?")
        _, _, tail = user.partition("# 待并入的新补丁")
        bullets = [ln for ln in tail.splitlines() if ln.strip().startswith("- ")]
        head, _, _ = user.partition("\n\n# 待并入的新补丁")
        head = head.replace("# 当前 ", "", 1)
        return "# merged\n\n" + head + "\n\n## 新增\n" + "\n".join(bullets) + "\n"


def _scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def _make_memory(tmp: Path) -> Path:
    mem = tmp / "memory"
    _write(mem / "dreaming" / "light" / f"{_today()}.md",
           "# Light\n"
           "- Candidate: User: 帮我抓网页提取关键词, use the `fetch_url` tool\n"
           "  - confidence: 0.6\n"
           "- Candidate: Assistant: 已完成抓取与关键词提取。\n"
           "  - confidence: 0.6\n"
           "- Candidate: User: 以后回答简短点\n"
           "  - confidence: 0.7\n")
    return mem


def test_full_cycle_mount_and_route_merge() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mem = _make_memory(tmp)
        live = tmp / "skills"
        live.mkdir()
        _write(live / "schedule-reminder" / "SKILL.md",
               '---\nname: schedule-reminder\ndescription: "提醒我 安排 出发 调度"\n---\n# x\n')
        staging = tmp / ".staging_skills"
        # workspace 根 (= identity_path.parent): 预置 IDENTITY.md / USER.md, 不建 SOUL.md
        identity = tmp / "IDENTITY.md"
        _write(identity, "# IDENTITY.md\n\n- **Name:** Franziska\n")
        _write(tmp / "USER.md", "# USER.md\n\n- 主人: Hausmeister\n")

        gw = MockGatewayMerge()
        merger = MockFileMerger()
        res = ms.run_satellite_cycle(
            hours=72, source="markdown", memory_dir=mem,
            gateway_client=gw, forge_client=MockForge(), identity_client=merger,
            staging_dir=staging, live_skills_dir=live, identity_path=identity,
            input_fn=_scripted(["Y"]),
        )
        assert res.status == "mounted", res
        # 去重清单与能力快照已注入网关上下文 (catalog 经 ASCII 安全化后中文标题会替换)
        assert "schedule-reminder" in gw.last_user
        assert "# " in gw.last_user and "<CAPABILITY_SNAPSHOT>" in gw.last_user
        assert "<RETRIEVED_MEMORY>" in gw.last_user
        # 技能挂载到与 memory 同级的 skills/
        assert (live / "web-keyword-extractor" / "executor.py").exists()

        # 三个文件按 target 路由写入
        assert "用户近期在做网页信息抽取" in (tmp / "USER.md").read_text(encoding="utf-8")
        assert "偏好简短直接的回答" in (tmp / "SOUL.md").read_text(encoding="utf-8")
        assert "自称 Franziska" in identity.read_text(encoding="utf-8")

        # 已存在的文件经 LLM 合并 (走 client) 且留 .bak; 新建的 SOUL.md 无 .bak
        assert "IDENTITY.md" in merger.files_seen and "USER.md" in merger.files_seen
        assert (tmp / "IDENTITY.md.bak").exists()
        assert (tmp / "USER.md.bak").exists()
        assert not (tmp / "SOUL.md.bak").exists(), "新建文件不应有 .bak"

        # 沙盒清空
        assert not staging.exists()


def test_full_cycle_ignore() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mem = _make_memory(tmp)
        res = ms.run_satellite_cycle(
            hours=72, source="markdown", memory_dir=mem,
            gateway_client=MockGatewayIgnore(), forge_client=MockForge(),
            staging_dir=tmp / ".staging_skills", live_skills_dir=tmp / "skills",
            identity_path=tmp / "IDENTITY.md",
            input_fn=_scripted([]),
        )
        assert res.status == "ignored", res


def test_no_logs_empty_memory() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        res = ms.run_satellite_cycle(
            hours=72, source="markdown", memory_dir=tmp / "memory_missing",
            gateway_client=MockGatewayMerge(), forge_client=MockForge(),
            staging_dir=tmp / ".staging_skills", live_skills_dir=tmp / "skills",
            identity_path=tmp / "IDENTITY.md",
            input_fn=_scripted([]),
        )
        assert res.status == "no_logs", res


def test_apply_routes_dedup_fallback() -> None:
    """无 identity_client 时走确定性追加, 仍按 target 分流到各文件."""
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        patches = [
            {"target": "AGENTS.md", "content": "先出计划再动手"},
            {"target": "USER.md", "content": "用户喜欢中文"},
        ]
        written = _apply_identity_updates(patches, identity_dir=d, client=None)
        assert set(written) == {"AGENTS.md", "USER.md"}
        assert "先出计划再动手" in (d / "AGENTS.md").read_text(encoding="utf-8")
        assert "用户喜欢中文" in (d / "USER.md").read_text(encoding="utf-8")


def test_apply_routes_skips_duplicate_only_patch() -> None:
    """补丁已存在时不重写文件, 也不把文件计入 written."""
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        _write(d / "USER.md", "# USER\n- 用户喜欢中文\n")
        written = _apply_identity_updates(
            [{"target": "USER.md", "content": "用户喜欢中文"}],
            identity_dir=d,
            client=None,
        )
        assert written == []
        assert not (d / "USER.md.bak").exists()


def test_dedup_append_unit() -> None:
    out = _dedup_append("USER.md", ["a-new-pref", "existing"], "# USER\n- existing\n")
    assert "a-new-pref" in out
    assert out.count("existing") == 1


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    checks = [
        ("full cycle mount + multi-file routing", test_full_cycle_mount_and_route_merge),
        ("full cycle ignore", test_full_cycle_ignore),
        ("no logs (empty memory)", test_no_logs_empty_memory),
        ("apply routes (dedup fallback)", test_apply_routes_dedup_fallback),
        ("apply routes skips duplicate-only patch", test_apply_routes_skips_duplicate_only_patch),
        ("dedup append unit", test_dedup_append_unit),
    ]
    failures = []
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
