"""
log_sniffer 测试: 重点验证新增的 Markdown 直读数据源.

    .venv/bin/python test_log_sniffer.py
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from log_sniffer import (
    clean_logs,
    fetch_recent_logs,
    fetch_recent_logs_markdown,
    sniff,
)

logger = logging.getLogger("test_log_sniffer")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _old_day() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")


DREAMING = """# Light Sleep

- Candidate: User: 帮我把这篇网页抓下来, use the `fetch_url` tool
  - confidence: 0.6
  - evidence: x:1-1
- Candidate: Assistant: 好的，已抓取并提取关键词。
  - confidence: 0.6
- Candidate: User: 以后回答简短点
  - confidence: 0.7
"""

NOTES = """# 2026 note

## 教训：先出 Plan
擅自决定不好，先列选项。

## 里程碑
获得灵魂。
"""


def test_markdown_candidate_parsing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = Path(tmp) / "memory"
        _write(mem / "dreaming" / "light" / f"{_today()}.md", DREAMING)
        rows = fetch_recent_logs_markdown(hours=72, memory_dir=mem)
        cleaned = clean_logs(rows)
        assert cleaned, "should parse candidate turns"
        # User/Assistant 配对
        joined_users = " ".join(c["user_intent"] for c in cleaned)
        assert "抓下来" in joined_users
        assert "以后回答简短点" in joined_users
        # 工具检测
        tools = [t["name"] for c in cleaned for t in c["tools_used"]]
        assert "fetch_url" in tools, tools


def test_markdown_notes_parsing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = Path(tmp) / "memory"
        _write(mem / f"{_today()}.md", NOTES)
        rows = fetch_recent_logs_markdown(hours=72, memory_dir=mem)
        cleaned = clean_logs(rows)
        intents = [c["user_intent"] for c in cleaned]
        assert "教训：先出 Plan" in intents
        assert "里程碑" in intents


def test_markdown_time_window() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = Path(tmp) / "memory"
        _write(mem / f"{_today()}.md", "# t\n## recent\nfresh")
        _write(mem / f"{_old_day()}.md", "# t\n## stale\nold")
        rows = fetch_recent_logs_markdown(hours=72, memory_dir=mem)
        bodies = " ".join(r["assistant_response"] for r in rows)
        assert "fresh" in bodies
        assert "old" not in bodies, "10-day-old file must be filtered out"


def test_missing_memory_dir_returns_empty() -> None:
    rows = fetch_recent_logs_markdown(hours=72, memory_dir="/nonexistent/xyz")
    assert rows == []


def test_sniff_markdown_default() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = Path(tmp) / "memory"
        _write(mem / "dreaming" / "rem" / f"{_today()}.md", DREAMING)
        result = sniff(hours=72, memory_dir=mem)  # source defaults to markdown
        assert result.fetched > 0
        assert result.cleaned
        assert isinstance(result.json, str) and result.json.startswith("[")


def test_fetch_dispatch_unknown_source() -> None:
    raised = False
    try:
        fetch_recent_logs(hours=72, source="weird")  # type: ignore[arg-type]
    except ValueError:
        raised = True
    assert raised


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    checks = [
        ("markdown candidate parsing", test_markdown_candidate_parsing),
        ("markdown notes parsing", test_markdown_notes_parsing),
        ("markdown time window", test_markdown_time_window),
        ("missing memory dir", test_missing_memory_dir_returns_empty),
        ("sniff markdown default", test_sniff_markdown_default),
        ("unknown source raises", test_fetch_dispatch_unknown_source),
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
