"""
skill_gateway.py — MetaSkill 运行时 Skill 网关

与 `gateway_router.py`(离线策略大脑) 不同, 本模块是**运行时**网关, 负责:

  1. 发现 / 编目  : 扫描技能根目录的 `*/SKILL.md`, 解析 frontmatter
                    (name / description / metadata.triggers / metadata.priority / tier).
  2. 触发匹配      : 给定用户输入, 按触发词与描述关键词打分, 返回候选.
  3. 优先级仲裁    : 多个命中时按 (priority, tier, score) 排序, 取最高.
  4. 热加载/卸载   : 运行时 load_skill / unload_skill / enable / disable / reload.
  5. 生命周期      : 维护启用状态; invoke() 动态加载技能的 executor.py 并调用 run().

另外提供 `build_skill_catalog()` —— 把现有技能压缩成清单文本, 供阶段二
`gateway_router.evaluate_habits(extra_user_context=...)` 做重复性检测(去重)。

技能分层 (tier) 与默认优先级:
  temporary(.staging_skills) = 30  >  user(工作区 skills/) = 20  >  builtin = 10
frontmatter `metadata.priority` 可显式覆盖。
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 工作区根 = .../workspace-hausmeister (本文件位于 skills/Satellite/meta_skill/)
WORKSPACE_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_USER_SKILLS_DIR: Path = WORKSPACE_ROOT / "skills"
DEFAULT_STAGING_DIR: Path = WORKSPACE_ROOT / "skills" / "Satellite" / "meta_skill" / ".staging_skills"

Tier = Literal["builtin", "user", "temporary"]
TIER_PRIORITY: dict[str, int] = {"temporary": 30, "user": 20, "builtin": 10}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_EN_RE = re.compile(r"[A-Za-z]{3,}")
_STOPWORDS = {
    "the", "and", "use", "when", "for", "with", "from", "like", "this", "that",
    "your", "you", "are", "any", "via", "set", "add", "out", "into", "all",
    "skill", "skills", "user", "agent", "activate", "detect", "data", "based",
}


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class SkillGatewayError(Exception):
    """skill_gateway 顶层异常."""


class SkillNotFoundError(SkillGatewayError):
    pass


class SkillInvocationError(SkillGatewayError):
    pass


# --------------------------------------------------------------------------- #
# frontmatter 解析
# --------------------------------------------------------------------------- #


def _extract_frontmatter(content: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _parse_frontmatter(content: str) -> dict[str, Any]:
    fm = _extract_frontmatter(content)
    if fm is None:
        return {}
    if yaml is not None:
        try:
            data = yaml.safe_load(fm)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError as exc:  # pragma: no cover
            logger.warning("Bad YAML frontmatter: %s", exc)
            return {}
    # 无 PyYAML 的极简回退: 只取顶层 key: value
    data2: dict[str, Any] = {}
    for line in fm.splitlines():
        if line[:1].isspace() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip().strip('"').strip("'")
        data2[k.strip()] = v
    return data2


def _derive_triggers(description: str) -> list[str]:
    """从描述里抽取候选触发词 (CJK 词 + 英文实词)."""
    triggers: list[str] = []
    triggers.extend(_CJK_RE.findall(description))
    for w in _EN_RE.findall(description):
        wl = w.lower()
        if wl not in _STOPWORDS:
            triggers.append(wl)
    seen: list[str] = []
    used: set[str] = set()
    for t in triggers:
        key = t.lower()
        if key not in used:
            used.add(key)
            seen.append(t)
    return seen[:40]


# --------------------------------------------------------------------------- #
# SkillRecord
# --------------------------------------------------------------------------- #


@dataclass
class SkillRecord:
    name: str
    description: str
    path: Path  # 技能目录
    tier: str = "user"
    priority: int = 0
    triggers: list[str] = field(default_factory=list)
    enabled: bool = True
    skill_md: Path | None = None

    @property
    def executor(self) -> Path:
        return self.path / "executor.py"

    def score(self, query: str) -> float:
        """对 query 的触发匹配分: 命中触发词的加权和 (按词长)."""
        q = query.lower()
        total = 0.0
        for t in self.triggers:
            if t.lower() in q:
                total += float(len(t))
        return total


def _load_skill_record(skill_md: Path, tier: str) -> SkillRecord | None:
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", skill_md, exc)
        return None

    fm = _parse_frontmatter(content)
    name = str(fm.get("name") or skill_md.parent.name).strip()
    description = str(fm.get("description") or "").strip()

    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    triggers_raw = meta.get("triggers")
    if isinstance(triggers_raw, str):
        triggers = [t.strip() for t in re.split(r"[,，;；]", triggers_raw) if t.strip()]
    elif isinstance(triggers_raw, list):
        triggers = [str(t).strip() for t in triggers_raw if str(t).strip()]
    else:
        triggers = _derive_triggers(description)

    try:
        priority = int(meta.get("priority", TIER_PRIORITY.get(tier, 0)))
    except (TypeError, ValueError):
        priority = TIER_PRIORITY.get(tier, 0)

    return SkillRecord(
        name=name,
        description=description,
        path=skill_md.parent,
        tier=tier,
        priority=priority,
        triggers=triggers,
        skill_md=skill_md,
    )


# --------------------------------------------------------------------------- #
# SkillGateway
# --------------------------------------------------------------------------- #


@dataclass
class SkillRoot:
    path: Path
    tier: str


class SkillGateway:
    """运行时技能注册表 + 触发匹配 + 优先级仲裁 + 热插拔."""

    def __init__(
        self,
        roots: Iterable[SkillRoot] | None = None,
        *,
        min_score: float = 1.0,
    ) -> None:
        self._skills: dict[str, SkillRecord] = {}
        self._roots: list[SkillRoot] = list(roots) if roots else [
            SkillRoot(DEFAULT_USER_SKILLS_DIR, "user"),
        ]
        self.min_score = min_score

    # ---- 发现 / 重载 -------------------------------------------------------- #

    def discover(self) -> int:
        """扫描所有 root, (重新)填充注册表. 返回技能数."""
        self._skills.clear()
        for root in self._roots:
            self._scan_root(root)
        logger.info("Gateway discovered %d skill(s).", len(self._skills))
        return len(self._skills)

    def _scan_root(self, root: SkillRoot) -> None:
        if not root.path.exists():
            return
        for skill_md in sorted(root.path.glob("*/SKILL.md")):
            rec = _load_skill_record(skill_md, root.tier)
            if rec is None:
                continue
            # 同名冲突: 高优先级覆盖
            existing = self._skills.get(rec.name)
            if existing is None or rec.priority >= existing.priority:
                self._skills[rec.name] = rec

    def reload(self) -> int:
        return self.discover()

    # ---- 热加载 / 卸载 ------------------------------------------------------ #

    def load_skill(self, skill_dir: Path | str, *, tier: str = "user") -> SkillRecord:
        """运行时加载单个技能目录 (含 SKILL.md). 已存在则覆盖."""
        skill_dir = Path(skill_dir)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise SkillNotFoundError(f"SKILL.md not found in {skill_dir}")
        rec = _load_skill_record(skill_md, tier)
        if rec is None:
            raise SkillGatewayError(f"Failed to load skill from {skill_dir}")
        self._skills[rec.name] = rec
        logger.info("Hot-loaded skill '%s' (tier=%s).", rec.name, tier)
        return rec

    def unload_skill(self, name: str) -> bool:
        rec = self._skills.pop(name, None)
        if rec is None:
            logger.info("unload_skill: '%s' not registered.", name)
            return False
        logger.info("Unloaded skill '%s'.", name)
        return True

    def enable(self, name: str) -> None:
        self._require(name).enabled = True

    def disable(self, name: str) -> None:
        self._require(name).enabled = False

    # ---- 查询 / 仲裁 -------------------------------------------------------- #

    def _require(self, name: str) -> SkillRecord:
        rec = self._skills.get(name)
        if rec is None:
            raise SkillNotFoundError(f"Skill not registered: {name}")
        return rec

    def list_skills(self, *, enabled_only: bool = False) -> list[SkillRecord]:
        vals = list(self._skills.values())
        if enabled_only:
            vals = [r for r in vals if r.enabled]
        return sorted(vals, key=lambda r: (-r.priority, r.name))

    def match(self, query: str) -> list[tuple[SkillRecord, float]]:
        """返回所有命中(score>=min_score)的 (record, score), 已排序仲裁."""
        scored = [
            (r, r.score(query))
            for r in self._skills.values()
            if r.enabled
        ]
        hits = [(r, s) for r, s in scored if s >= self.min_score]
        # 仲裁: 先比 score, 再比 priority, 再比 tier 权重
        hits.sort(
            key=lambda rs: (rs[1], rs[0].priority, TIER_PRIORITY.get(rs[0].tier, 0)),
            reverse=True,
        )
        return hits

    def dispatch(self, query: str) -> SkillRecord | None:
        """返回最佳命中技能, 无命中返回 None."""
        hits = self.match(query)
        if not hits:
            logger.info("No skill matched query: %.40s", query)
            return None
        best, score = hits[0]
        logger.info("Dispatch -> '%s' (score=%.1f, tier=%s)", best.name, score, best.tier)
        return best

    # ---- 调用 (动态加载 executor.py) --------------------------------------- #

    def invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        rec = self._require(name)
        if not rec.enabled:
            raise SkillInvocationError(f"Skill '{name}' is disabled.")
        if not rec.executor.exists():
            raise SkillInvocationError(f"Skill '{name}' has no executor.py at {rec.executor}")

        mod_name = f"_satellite_skill_{re.sub(r'[^0-9A-Za-z_]', '_', rec.name)}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, rec.executor)
            if spec is None or spec.loader is None:
                raise SkillInvocationError(f"Cannot build import spec for {rec.executor}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            raise SkillInvocationError(f"Failed to import {rec.executor}: {exc}") from exc

        run = getattr(module, "run", None)
        if not callable(run):
            raise SkillInvocationError(f"Skill '{name}' executor.py has no callable run().")
        try:
            return run(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise SkillInvocationError(f"run() raised in '{name}': {exc}") from exc


# --------------------------------------------------------------------------- #
# 技能清单 (供阶段二去重)
# --------------------------------------------------------------------------- #


def scan_skills(
    roots: Iterable[SkillRoot] | None = None,
) -> list[SkillRecord]:
    """扫描 root 列表, 返回 SkillRecord 列表 (供编目/去重)."""
    gw = SkillGateway(roots=roots)
    gw.discover()
    return gw.list_skills()


def build_skill_catalog(
    roots: Iterable[SkillRoot] | None = None,
    *,
    max_desc: int = 220,
) -> str:
    """
    生成现有技能的紧凑清单文本, 用于喂给网关做重复性检测(去重).

    形如:
        # 现有技能清单 (生成新技能前必须比对去重)
        - name: schedule-reminder | tier: user
          triggers: 提醒我, 安排, 出发, 周四, 明天
          desc: Detect scheduling intents ...
    """
    records = scan_skills(roots)
    if not records:
        return "# 现有技能清单: (空)"
    lines = ["# 现有技能清单 (生成新技能前必须比对去重)"]
    for r in records:
        desc = r.description.replace("\n", " ").strip()
        if len(desc) > max_desc:
            desc = desc[: max_desc - 1].rstrip() + "…"
        trig = ", ".join(r.triggers[:8])
        lines.append(f"- name: {r.name} | tier: {r.tier}")
        if trig:
            lines.append(f"  triggers: {trig}")
        if desc:
            lines.append(f"  desc: {desc}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="MetaSkill runtime Skill Gateway.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List discovered skills.")
    p_list.add_argument("--skills-dir", default=str(DEFAULT_USER_SKILLS_DIR))

    p_match = sub.add_parser("match", help="Match a query against skills.")
    p_match.add_argument("query")
    p_match.add_argument("--skills-dir", default=str(DEFAULT_USER_SKILLS_DIR))

    p_cat = sub.add_parser("catalog", help="Print dedup catalog text.")
    p_cat.add_argument("--skills-dir", default=str(DEFAULT_USER_SKILLS_DIR))

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    roots = [SkillRoot(Path(args.skills_dir), "user")]

    if args.cmd == "list":
        gw = SkillGateway(roots=roots)
        gw.discover()
        for r in gw.list_skills():
            print(f"[{r.tier:9}] p{r.priority:<3} {r.name}: {r.description[:70]}")
        return 0
    if args.cmd == "match":
        gw = SkillGateway(roots=roots)
        gw.discover()
        for r, s in gw.match(args.query):
            print(f"score={s:5.1f}  {r.name}  (tier={r.tier}, p={r.priority})")
        best = gw.dispatch(args.query)
        print(f"\n=> best: {best.name if best else '(none)'}")
        return 0
    if args.cmd == "catalog":
        print(build_skill_catalog(roots))
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
