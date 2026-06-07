"""
skill_gateway 测试: 触发匹配 + 优先级仲裁 + 热加载/卸载 + 调用 + 去重清单.

    .venv/bin/python test_skill_gateway.py
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from skill_gateway import (
    SkillGateway,
    SkillRoot,
    SkillNotFoundError,
    build_skill_catalog,
)

logger = logging.getLogger("test_skill_gateway")


def _mk_skill(
    root: Path,
    name: str,
    description: str,
    *,
    triggers: list[str] | None = None,
    priority: int | None = None,
    run_returns: str = "ok",
) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta_lines = []
    if triggers is not None:
        meta_lines.append(f"  triggers: [{', '.join(triggers)}]")
    if priority is not None:
        meta_lines.append(f"  priority: {priority}")
    meta_block = ("metadata:\n" + "\n".join(meta_lines) + "\n") if meta_lines else ""
    (d / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\n{meta_block}---\n\n# {name}\n',
        encoding="utf-8",
    )
    (d / "executor.py").write_text(
        f'def run(*a, **k):\n    return "{run_returns}"\n', encoding="utf-8"
    )
    return d


def test_discover_and_match() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _mk_skill(root, "schedule-reminder",
                  "Detect scheduling intents 提醒我 安排 出发 周四 明天")
        _mk_skill(root, "web-summarizer",
                  "Fetch a web page and summarize 抓取 网页 摘要")
        gw = SkillGateway(roots=[SkillRoot(root, "user")])
        assert gw.discover() == 2
        best = gw.dispatch("提醒我明天去开会")
        assert best is not None and best.name == "schedule-reminder", best
        best2 = gw.dispatch("帮我抓取这个网页做摘要")
        assert best2 is not None and best2.name == "web-summarizer", best2
        assert gw.dispatch("今天天气如何") is None  # 无触发


def test_priority_arbitration() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        user_root = Path(tmp) / "skills"
        temp_root = Path(tmp) / ".staging_skills"
        # 两个技能共享触发词 "部署", 但 tier/priority 不同
        _mk_skill(user_root, "deploy-basic", "部署 服务器 deploy", triggers=["部署"])
        _mk_skill(temp_root, "deploy-pro", "部署 服务器 升级版", triggers=["部署"], priority=99)
        gw = SkillGateway(roots=[
            SkillRoot(user_root, "user"),
            SkillRoot(temp_root, "temporary"),
        ])
        gw.discover()
        best = gw.dispatch("帮我部署")
        # 同名? 不同名. score 相同 -> 比 priority -> deploy-pro(99) 胜
        assert best is not None and best.name == "deploy-pro", best


def test_hot_load_unload_disable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        gw = SkillGateway(roots=[SkillRoot(root, "user")])
        gw.discover()
        assert gw.list_skills() == []

        sk = _mk_skill(root, "note-taker", "记笔记 note 记录", triggers=["记笔记"])
        rec = gw.load_skill(sk)  # 热加载
        assert rec.name == "note-taker"
        assert gw.dispatch("帮我记笔记") is not None

        gw.disable("note-taker")  # 生命周期: 禁用 -> 不再匹配
        assert gw.dispatch("帮我记笔记") is None
        gw.enable("note-taker")
        assert gw.dispatch("帮我记笔记") is not None

        assert gw.unload_skill("note-taker") is True  # 热卸载
        assert gw.dispatch("帮我记笔记") is None
        assert gw.unload_skill("ghost") is False


def test_invoke_executor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _mk_skill(root, "echoer", "回声 echo", triggers=["回声"], run_returns="ECHOED")
        gw = SkillGateway(roots=[SkillRoot(root, "user")])
        gw.discover()
        assert gw.invoke("echoer") == "ECHOED"
        raised = False
        try:
            gw.invoke("nope")
        except SkillNotFoundError:
            raised = True
        assert raised


def test_build_catalog() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        _mk_skill(root, "schedule-reminder",
                  "Detect scheduling intents 提醒我 安排", triggers=["提醒我", "安排"])
        cat = build_skill_catalog([SkillRoot(root, "user")])
        assert "schedule-reminder" in cat
        assert "提醒我" in cat
        assert cat.startswith("# 现有技能清单")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    checks = [
        ("discover & match", test_discover_and_match),
        ("priority arbitration", test_priority_arbitration),
        ("hot load/unload/disable", test_hot_load_unload_disable),
        ("invoke executor", test_invoke_executor),
        ("build dedup catalog", test_build_catalog),
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
        print(f"{len(failures)} failure(s)")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
