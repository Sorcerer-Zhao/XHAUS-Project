"""
log_sniffer.py — MetaSkill 阶段一：嗅探与聚合

职责
----
1. 直读本地 Markdown 记忆日志 (默认数据源), 或可选 SQLite `interaction_logs` 表。
2. 提取过去 N 小时（默认 72h / 3 天）的全部对话记录，
   包含纯对话和带 `tool_calls` 的记录。
3. 清洗并序列化为紧凑 JSON 数组，仅保留下列字段：
   - timestamp
   - user_intent       (用户输入)
   - tools_used        (工具调用序列, list[dict])
   - assistant_response

数据源 (source)
---------------
- "markdown" (默认): 直读 OpenClaw 工作区的 Markdown 记忆:
    * memory/YYYY-MM-DD.md            —— 每日精炼笔记 (按 ## 小节拆成记录)
    * memory/dreaming/**/*.md         —— 含 `Candidate: User:` / `Candidate: Assistant:`
                                          的对话候选, 解析成 user/assistant 配对
  工具调用从文本里启发式抽取 (形如 ``use the `xxx` tool``).
- "sqlite": 旧路径, 读 `interaction_logs` 表 (列名可经 ColumnMap 适配)。

SQLite 表结构 (source="sqlite" 时)
----------------------------------
CREATE TABLE interaction_logs (
    id                INTEGER PRIMARY KEY,
    timestamp         TEXT     NOT NULL,   -- ISO-8601 字符串或 Unix 时间戳
    user_input        TEXT,
    assistant_response TEXT,
    tool_calls        TEXT                 -- JSON 字符串
);
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, Sequence, TypedDict

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 常量 / 默认配置
# --------------------------------------------------------------------------- #

# 工作区根 = .../workspace-hausmeister (本文件在 skills/Satellite/ 下)
WORKSPACE_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_MEMORY_DIR: Path = WORKSPACE_ROOT / "memory"
DEFAULT_DB_PATH: Path = WORKSPACE_ROOT / "logs.db"
DEFAULT_TABLE: str = "interaction_logs"
DEFAULT_HOURS: int = 72
DEFAULT_SOURCE: "Literal['markdown', 'sqlite']" = "markdown"

# 单字段最大字符数, 防止超长 assistant 回复撑爆 token 预算
MAX_FIELD_CHARS: int = 800


@dataclass(frozen=True)
class ColumnMap:
    """物理列名到逻辑字段名的映射, 便于跨 schema 复用."""

    timestamp: str = "timestamp"
    user_input: str = "user_input"
    assistant_response: str = "assistant_response"
    tool_calls: str = "tool_calls"


DEFAULT_COLUMNS: ColumnMap = ColumnMap()


# --------------------------------------------------------------------------- #
# 类型定义
# --------------------------------------------------------------------------- #


class ToolCall(TypedDict, total=False):
    name: str
    args: dict[str, Any]
    result: Any


class CleanedLog(TypedDict):
    timestamp: str
    user_intent: str
    tools_used: list[ToolCall]
    assistant_response: str


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class LogSnifferError(Exception):
    """log_sniffer 顶层异常."""


class DatabaseConnectionError(LogSnifferError):
    """无法连接到 SQLite 数据库."""


class SchemaError(LogSnifferError):
    """目标表或列缺失."""


class RecordParseError(LogSnifferError):
    """单条记录解析失败 (默认会被吞掉并打 warning)."""


# --------------------------------------------------------------------------- #
# 数据库辅助
# --------------------------------------------------------------------------- #


@contextmanager
def _open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """以只读方式打开 SQLite, 失败抛出 `DatabaseConnectionError`."""
    if not db_path.exists():
        raise DatabaseConnectionError(f"SQLite database not found: {db_path}")

    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise DatabaseConnectionError(
            f"Failed to open SQLite database at {db_path}: {exc}"
        ) from exc

    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: ColumnMap
) -> None:
    """校验表及关键列是否存在, 否则抛 `SchemaError`."""
    try:
        cursor = conn.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in cursor.fetchall()}
    except sqlite3.Error as exc:
        raise SchemaError(f"Failed to inspect table '{table}': {exc}") from exc

    if not existing:
        raise SchemaError(f"Table '{table}' does not exist or is empty schema.")

    required = {
        columns.timestamp,
        columns.user_input,
        columns.assistant_response,
        columns.tool_calls,
    }
    missing = required - existing
    if missing:
        raise SchemaError(
            f"Table '{table}' missing required columns: {sorted(missing)}"
        )


# --------------------------------------------------------------------------- #
# Markdown 数据源 (默认)
# --------------------------------------------------------------------------- #

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# 形如:  use the `message` tool   /   `fetch_url` tool
_TOOL_RE = re.compile(r"`([A-Za-z][\w\-]{1,40})`\s*(?:tool\b)?", re.IGNORECASE)
_TOOL_PHRASE_RE = re.compile(r"use the `([A-Za-z][\w\-]{1,40})` tool", re.IGNORECASE)
_CANDIDATE_RE = re.compile(r"^\s*-\s*Candidate:\s*(User|Assistant)\s*:\s*(.*)$")


def _file_date(path: Path) -> datetime:
    """从文件名解析 YYYY-MM-DD (UTC 当日 00:00); 失败回退到 mtime."""
    m = _DATE_RE.search(path.stem)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _truncate(text: str, limit: int = MAX_FIELD_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _detect_tools(text: str) -> list[ToolCall]:
    """从自由文本里启发式抽取被提及的工具名."""
    names: list[str] = []
    for m in _TOOL_PHRASE_RE.finditer(text):
        names.append(m.group(1))
    # 仅当紧跟 'tool' 字样时才把反引号词当工具, 避免误抓代码片段
    for m in re.finditer(r"`([A-Za-z][\w\-]{1,40})`\s+tool\b", text):
        names.append(m.group(1))
    seen: list[ToolCall] = []
    used: set[str] = set()
    for n in names:
        key = n.lower()
        if key not in used:
            used.add(key)
            seen.append({"name": n})
    return seen


def _iter_memory_files(memory_dir: Path, include_dreaming: bool) -> Iterator[Path]:
    if not memory_dir.exists():
        return
    yield from sorted(memory_dir.glob("*.md"))
    if include_dreaming:
        dreaming = memory_dir / "dreaming"
        if dreaming.exists():
            yield from sorted(dreaming.rglob("*.md"))


def _parse_candidate_file(text: str, file_dt: datetime) -> list[dict[str, Any]]:
    """解析 dreaming 候选文件 (User/Assistant 轮次) 为配对记录."""
    iso = file_dt.isoformat()
    turns: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = _CANDIDATE_RE.match(line)
        if m:
            turns.append((m.group(1).lower(), m.group(2).strip()))

    records: list[dict[str, Any]] = []
    pending_user: str | None = None
    for role, content in turns:
        if role == "user":
            if pending_user is not None:
                records.append(_mk_record(iso, pending_user, ""))
            pending_user = content
        else:  # assistant
            user_text = pending_user or ""
            records.append(_mk_record(iso, user_text, content))
            pending_user = None
    if pending_user is not None:
        records.append(_mk_record(iso, pending_user, ""))
    return records


def _parse_notes_file(text: str, file_dt: datetime) -> list[dict[str, Any]]:
    """解析每日笔记 (按 ## 小节拆分) 为记录, 小节标题作为 user_intent."""
    iso = file_dt.isoformat()
    records: list[dict[str, Any]] = []
    title = ""
    section: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if section is None:
            return
        body = "\n".join(buf).strip()
        records.append(_mk_record(iso, section, body))

    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            section = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    flush()

    if not records and text.strip():  # 没有小节就整篇作为一条
        records.append(_mk_record(iso, title or "note", text.strip()))
    return records


def _mk_record(iso: str, user_text: str, assistant_text: str) -> dict[str, Any]:
    combined = f"{user_text}\n{assistant_text}"
    return {
        "timestamp": iso,
        "user_input": _truncate(user_text),
        "assistant_response": _truncate(assistant_text),
        "tool_calls": _detect_tools(combined),
    }


def fetch_recent_logs_markdown(
    hours: int = DEFAULT_HOURS,
    *,
    memory_dir: Path | str = DEFAULT_MEMORY_DIR,
    include_dreaming: bool = True,
) -> list[dict[str, Any]]:
    """
    直读 Markdown 记忆日志, 返回与 `clean_logs` 兼容的 dict 行 (按时间倒序).

    记忆目录不存在时返回空列表 (不抛异常), 交由上层按 "无日志" 处理.
    """
    if hours <= 0:
        raise ValueError(f"`hours` must be positive, got {hours!r}")

    memory_dir = Path(memory_dir)
    if not memory_dir.exists():
        logger.info("Memory dir not found: %s (no markdown logs).", memory_dir)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    files_used = 0

    for path in _iter_memory_files(memory_dir, include_dreaming):
        file_dt = _file_date(path)
        if file_dt < cutoff:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            continue

        if _CANDIDATE_RE.search(text) or "- Candidate:" in text:
            parsed = _parse_candidate_file(text, file_dt)
        else:
            parsed = _parse_notes_file(text, file_dt)
        rows.extend(parsed)
        files_used += 1

    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    logger.info(
        "Markdown source: %d record(s) from %d file(s) under %s (last %dh)",
        len(rows),
        files_used,
        memory_dir,
        hours,
    )
    return rows


# --------------------------------------------------------------------------- #
# 主要 API
# --------------------------------------------------------------------------- #


def fetch_recent_logs(
    hours: int = DEFAULT_HOURS,
    *,
    source: "Literal['markdown', 'sqlite']" = DEFAULT_SOURCE,
    memory_dir: Path | str = DEFAULT_MEMORY_DIR,
    include_dreaming: bool = True,
    db_path: Path | str = DEFAULT_DB_PATH,
    table: str = DEFAULT_TABLE,
    columns: ColumnMap = DEFAULT_COLUMNS,
) -> list[dict[str, Any]] | list[sqlite3.Row]:
    """
    提取过去 `hours` 小时内的全部对话记录 (含 tool_calls).

    参数
    ----
    hours: int
        时间窗口, 默认 72 (= 3 天).
    source: "markdown" | "sqlite"
        数据源, 默认 "markdown" (直读记忆日志).
    memory_dir: Path | str
        markdown 源的记忆目录, 默认 工作区 memory/.
    include_dreaming: bool
        markdown 源是否纳入 memory/dreaming/**.
    db_path / table / columns:
        source="sqlite" 时使用.

    返回
    ----
    markdown 源 -> list[dict]; sqlite 源 -> list[sqlite3.Row].
    两者皆可直接交给 `clean_logs`.
    """
    if hours <= 0:
        raise ValueError(f"`hours` must be positive, got {hours!r}")

    if source == "markdown":
        return fetch_recent_logs_markdown(
            hours, memory_dir=memory_dir, include_dreaming=include_dreaming
        )
    if source != "sqlite":
        raise ValueError(f"Unknown source: {source!r} (use 'markdown' or 'sqlite')")

    db_path = Path(db_path)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    cutoff_epoch = cutoff.timestamp()

    # 兼容两种 timestamp 存法: ISO 字符串 或 Unix 数值.
    query = (
        f"SELECT {columns.timestamp}        AS timestamp, "
        f"       {columns.user_input}        AS user_input, "
        f"       {columns.assistant_response} AS assistant_response, "
        f"       {columns.tool_calls}        AS tool_calls "
        f"FROM   {table} "
        f"WHERE  ( typeof({columns.timestamp}) = 'text'    "
        f"         AND {columns.timestamp} >= ? )          "
        f"    OR ( typeof({columns.timestamp}) IN ('integer','real') "
        f"         AND {columns.timestamp} >= ? )          "
        f"ORDER BY {columns.timestamp} DESC"
    )

    with _open_db(db_path) as conn:
        _ensure_columns(conn, table, columns)
        try:
            cursor = conn.execute(query, (cutoff_iso, cutoff_epoch))
            rows: list[sqlite3.Row] = cursor.fetchall()
        except sqlite3.Error as exc:
            raise LogSnifferError(
                f"Failed to query recent logs from '{table}': {exc}"
            ) from exc

    logger.info("Fetched %d log rows from %s (last %dh)", len(rows), table, hours)
    return rows


# --------------------------------------------------------------------------- #
# 清洗 / 序列化
# --------------------------------------------------------------------------- #


def _normalize_timestamp(raw: Any) -> str:
    """统一为 ISO-8601 (UTC) 字符串. 解析失败返回原值字符串形式."""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return str(raw)
    if isinstance(raw, str):
        return raw.strip()
    return str(raw)


def _parse_tool_calls(raw: Any) -> list[ToolCall]:
    """
    解析 `tool_calls` 字段. 支持以下输入:
      - None / 空串                 -> []
      - JSON 数组字符串             -> 直接 loads
      - JSON 对象字符串 (单次调用) -> [obj]
      - 已经是 list / dict          -> 原样规整
    """
    if raw is None or raw == "":
        return []

    if isinstance(raw, (list, dict)):
        parsed: Any = raw
    elif isinstance(raw, (bytes, bytearray)):
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordParseError(f"Invalid tool_calls bytes: {exc}") from exc
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RecordParseError(f"Invalid tool_calls JSON: {exc}") from exc
    else:
        raise RecordParseError(f"Unsupported tool_calls type: {type(raw).__name__}")

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise RecordParseError(
            f"tool_calls must decode to list/dict, got {type(parsed).__name__}"
        )

    cleaned: list[ToolCall] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        call: ToolCall = {}
        if "name" in item and item["name"] is not None:
            call["name"] = str(item["name"])
        if "args" in item and isinstance(item["args"], dict):
            call["args"] = item["args"]
        if "result" in item:
            call["result"] = item["result"]
        if call:
            cleaned.append(call)
    return cleaned


def clean_logs(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> list[CleanedLog]:
    """
    将原始行清洗为 `CleanedLog` 列表, 单行解析失败仅记录 warning, 不影响其他行.
    """
    cleaned: list[CleanedLog] = []
    for idx, row in enumerate(rows):
        try:
            mapping: dict[str, Any] = (
                dict(row) if isinstance(row, sqlite3.Row) else dict(row)
            )
            tools = _parse_tool_calls(mapping.get("tool_calls"))
            cleaned.append(
                CleanedLog(
                    timestamp=_normalize_timestamp(mapping.get("timestamp")),
                    user_intent=(mapping.get("user_input") or "").strip(),
                    tools_used=tools,
                    assistant_response=(
                        mapping.get("assistant_response") or ""
                    ).strip(),
                )
            )
        except RecordParseError as exc:
            logger.warning("Skip row #%d due to parse error: %s", idx, exc)
        except Exception as exc:  # noqa: BLE001 — 兜底, 防止单点污染整批
            logger.warning("Skip row #%d due to unexpected error: %s", idx, exc)
    return cleaned


def serialize_logs(cleaned: Sequence[CleanedLog]) -> str:
    """
    将清洗后的日志序列化为紧凑 JSON 字符串 (无多余空白, 保留中文).
    """
    return json.dumps(
        list(cleaned),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )


# --------------------------------------------------------------------------- #
# 顶层便捷函数
# --------------------------------------------------------------------------- #


@dataclass
class SnifferResult:
    """聚合输出, 便于阶段二消费."""

    fetched: int
    cleaned: list[CleanedLog] = field(default_factory=list)

    @property
    def json(self) -> str:
        return serialize_logs(self.cleaned)


def sniff(
    hours: int = DEFAULT_HOURS,
    *,
    source: "Literal['markdown', 'sqlite']" = DEFAULT_SOURCE,
    memory_dir: Path | str = DEFAULT_MEMORY_DIR,
    include_dreaming: bool = True,
    db_path: Path | str = DEFAULT_DB_PATH,
    table: str = DEFAULT_TABLE,
    columns: ColumnMap = DEFAULT_COLUMNS,
) -> SnifferResult:
    """阶段一 one-shot 入口: 取数 -> 清洗 -> 打包. 默认直读 Markdown 记忆."""
    rows = fetch_recent_logs(
        hours=hours,
        source=source,
        memory_dir=memory_dir,
        include_dreaming=include_dreaming,
        db_path=db_path,
        table=table,
        columns=columns,
    )
    cleaned = clean_logs(rows)
    return SnifferResult(fetched=len(rows), cleaned=cleaned)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MetaSkill Phase 1 — sniff recent interaction logs."
    )
    parser.add_argument(
        "--source",
        choices=["markdown", "sqlite"],
        default=DEFAULT_SOURCE,
        help=f"Data source (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "--memory",
        type=Path,
        default=DEFAULT_MEMORY_DIR,
        help=f"Markdown memory dir (default: {DEFAULT_MEMORY_DIR})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--table", default=DEFAULT_TABLE, help=f"Table name (default: {DEFAULT_TABLE})"
    )
    parser.add_argument(
        "--hours", type=int, default=DEFAULT_HOURS, help="Lookback window in hours."
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON instead of compact."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable DEBUG logging."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        result = sniff(
            hours=args.hours,
            source=args.source,
            memory_dir=args.memory,
            db_path=args.db,
            table=args.table,
        )
    except LogSnifferError as exc:
        logger.error("Sniff failed: %s", exc)
        return 1
    except ValueError as exc:
        logger.error("Bad argument: %s", exc)
        return 2

    if args.pretty:
        sys.stdout.write(
            json.dumps(result.cleaned, ensure_ascii=False, indent=2) + "\n"
        )
    else:
        sys.stdout.write(result.json + "\n")

    logger.info("Done. fetched=%d cleaned=%d", result.fetched, len(result.cleaned))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
