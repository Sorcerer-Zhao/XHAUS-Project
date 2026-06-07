"""
main_satellite.py — MetaSkill 阶段四: 主动推送与挂载 (主入口)

把阶段一~三组装成一条完整的轨道观测周期:

    嗅探 (log_sniffer)
        -> 研判 (gateway_router.evaluate_habits)
        -> 暂存 (executor_bridge.generate_skill_to_staging / stage_identity_update)
        -> Human-in-the-Loop 终端确认
        -> 挂载到正式 skills/ + 按 target 并入 IDENTITY/SOUL/AGENTS/USER.md
           /  丢弃清理  /  回炉重构

直接运行 (默认走 DeepSeek, 见 README『接入 DeepSeek / OpenClaw』):
    DEEPSEEK_API_KEY=sk-... python main_satellite.py --hours 72
LLM 客户端由 gateway_router.make_llm_client() 按 env/参数构造.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from log_sniffer import (
    DEFAULT_HOURS,
    DEFAULT_MEMORY_DIR,
    LogSnifferError,
    DatabaseConnectionError,
    sniff,
)
from gateway_router import (
    GatewayDecision,
    LLMClient,
    LLMResponseError,
    evaluate_habits,
    make_llm_client,
)
from executor_bridge import (
    DEFAULT_STAGING_DIR,
    PROJECT_ROOT,
    StagingResult,
    generate_skill_to_staging,
    normalize_patches,
    stage_identity_update,
)
from skill_gateway import SkillRoot, build_skill_catalog

logger = logging.getLogger("satellite")

# --------------------------------------------------------------------------- #
# 路径常量
# --------------------------------------------------------------------------- #

# PROJECT_ROOT = .../skills/Satellite/meta_skill (来自 executor_bridge)
# 正式技能目录: meta_skill -> Satellite -> skills (即 .../skills/)
LIVE_SKILLS_DIR: Path = PROJECT_ROOT.parent.parent
# 工作区根 = skills/ 的上一级 (即 .../workspace-hausmeister/)
WORKSPACE_ROOT: Path = LIVE_SKILLS_DIR.parent
# 身份预设文件: 与 skills/ 同级的工作区 IDENTITY.md (用户确认)
DEFAULT_IDENTITY_PATH: Path = WORKSPACE_ROOT / "IDENTITY.md"

BANNER_WIDTH = 50
RULE = "=" * BANNER_WIDTH

InputFn = Callable[[str], str]


# --------------------------------------------------------------------------- #
# 周期结果
# --------------------------------------------------------------------------- #


@dataclass
class CycleResult:
    status: str  # no_logs | ignored | mounted | discarded | aborted | error
    detail: str = ""

    def __str__(self) -> str:
        return f"CycleResult(status={self.status!r}, detail={self.detail!r})"


# --------------------------------------------------------------------------- #
# 终端展示
# --------------------------------------------------------------------------- #


def _format_patches(patches: list[dict[str, str]]) -> str:
    if not patches:
        return "无"
    return "\n              ".join(
        f"- [{p.get('target', 'IDENTITY.md')}] {p.get('content', '')}" for p in patches
    )


def _print_report(
    decision: GatewayDecision,
    staging: StagingResult | None,
    patches: list[dict[str, str]],
) -> None:
    sg = decision.skill_generation
    lines: list[str] = [RULE, "🛰️ Satellite 轨道观测报告"]

    if staging is not None and sg.action in ("merge", "upgrade"):
        verb = "合并生成" if sg.action == "merge" else "升级"
        lines.append(f"发现新行为模式！拟{verb}技能：【{staging.target_name}】")
        lines.append(f"作用：{sg.description or '(无描述)'}")
        qc = "✅ 通过" if staging.valid else f"⚠️ 未通过 ({staging.validation_message})"
        cc = "✅ 通过" if staging.compiled else f"⚠️ 未通过 ({staging.compile_message})"
        lines.append(f"质量关卡：原厂质检 {qc} ｜ 编译检测 {cc}")
        lines.append(f"沙盒文件：{', '.join(staging.files)}")
    else:
        lines.append("本周期无新技能生成。")

    lines.append(f"认知预设更新：{_format_patches(patches)}")
    lines.append(RULE)
    print("\n".join(lines))


# --------------------------------------------------------------------------- #
# 挂载 / 清理 / 身份写入
# --------------------------------------------------------------------------- #


def _mount_skill(skill_dir: Path, live_skills_dir: Path) -> Path:
    """shutil.move 把沙盒技能挪到正式 skills/ 目录, 返回目标路径."""
    live_skills_dir.mkdir(parents=True, exist_ok=True)
    target = live_skills_dir / skill_dir.name
    if target.exists():
        raise FileExistsError(
            f"正式目录已存在同名技能, 拒绝覆盖: {target} (请先手动处理)"
        )
    shutil.move(str(skill_dir), str(target))
    logger.info("Mounted skill -> %s", target)
    return target


# 四个可路由的身份/认知文件及其"角色", 用于生成针对性的合并 Prompt.
TARGET_FILES: tuple[str, ...] = ("IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md")
_FILE_ROLES: dict[str, str] = {
    "IDENTITY.md": "管家的人设/名字/对外调性 (我是谁)",
    "SOUL.md": "管家的灵魂/价值观/语气与说话方式 (我如何存在与表达)",
    "AGENTS.md": "工作方法论/操作规则/流程约定 (我该怎么做事)",
    "USER.md": "关于主人(用户)本人的事实与偏好 (用户在做什么、喜欢/忌讳什么)",
}


def _merge_system_prompt(filename: str) -> str:
    role = _FILE_ROLES.get(filename, "身份/认知预设")
    return (
        f"你在维护一个 AI 管家的文件 {filename} (Markdown).\n"
        f"该文件的职责是: {role}.\n"
        "现在有若干条新的补丁需要并入。\n\n"
        "要求:\n"
        f"- 输出**完整的**更新后 {filename} 全文 (Markdown), 不要任何解释或围栏.\n"
        "- 若某条补丁与文件里已有内容**语义相近**, 请润色后**合并**为一条, 不要重复堆叠.\n"
        "- 若是全新内容, 追加到最合适的小节 (没有就新建一个贴切的小节).\n"
        "- 严禁删除与补丁无关的既有内容, 保留原有结构与设定.\n"
        "- 保持简洁克制, 用中文.\n"
    )


def _fresh_patches(patches: list[str], existing: str) -> list[str]:
    """返回当前文件中尚未出现过的非空补丁."""
    existing_norm = existing.lower()
    return [
        p.strip()
        for p in patches
        if p.strip() and p.strip().lower() not in existing_norm
    ]


def _dedup_append(filename: str, patches: list[str], existing: str) -> str:
    """无 LLM 时的确定性回退: 跳过与既有内容明显重复的补丁后追加."""
    fresh = _fresh_patches(patches, existing)
    if not fresh:
        return existing

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = [f"\n## Satellite 更新 ({ts})", ""]
    block += [f"- {p}" for p in fresh]
    block.append("")
    title = filename.replace(".md", "")
    head = existing if existing.strip() else f"# {title}\n"
    if existing.strip() and not existing.endswith("\n"):
        head += "\n"
    return head + "\n".join(block) + "\n"


def _merge_one_file(
    filename: str,
    patches: list[str],
    target_path: Path,
    *,
    client: LLMClient | None,
) -> bool:
    """把同属一个文件的补丁并入该文件. 发生实际写入时返回 True."""
    if not patches:
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if target_path.exists():
        existing = target_path.read_text(encoding="utf-8")

    fresh = _fresh_patches(patches, existing)
    if not fresh:
        logger.info("%s has no fresh identity patches; skipping write.", filename)
        return False

    if target_path.exists():
        backup = target_path.with_suffix(target_path.suffix + ".bak")
        backup.write_text(existing, encoding="utf-8")
        logger.info("Backed up %s -> %s", target_path.name, backup.name)

    new_content: str | None = None
    if client is not None and existing.strip():
        user = (
            f"# 当前 {filename}\n{existing}\n\n"
            "# 待并入的新补丁\n" + "\n".join(f"- {p}" for p in fresh)
        )
        try:
            raw = client.complete(system=_merge_system_prompt(filename), user=user)
            cand = raw.strip()
            if cand.startswith("```"):
                cand = cand.split("\n", 1)[-1]
                if cand.rstrip().endswith("```"):
                    cand = cand.rstrip()[:-3]
            if cand.strip():
                new_content = cand.rstrip() + "\n"
                logger.info("%s merged via LLM polish.", filename)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM merge for %s failed (%s); falling back to dedup append.", filename, exc)

    if new_content is None:
        new_content = _dedup_append(filename, fresh, existing)
        logger.info("%s merged via deterministic dedup-append.", filename)

    target_path.write_text(new_content, encoding="utf-8")
    logger.info("Wrote %d fresh patch(es) -> %s", len(fresh), target_path)
    return True


def _apply_identity_updates(
    patches: list[dict[str, str]],
    *,
    identity_dir: Path,
    client: LLMClient | None = None,
) -> list[str]:
    """
    按 target 把补丁分组, 分别并入 identity_dir 下对应的文件
    (IDENTITY/SOUL/AGENTS/USER.md). 返回实际被写入的文件名列表.
    """
    if not patches:
        return []
    grouped: dict[str, list[str]] = {}
    for p in patches:
        target = p.get("target", "IDENTITY.md")
        if target not in TARGET_FILES:
            target = "IDENTITY.md"
        grouped.setdefault(target, []).append(p.get("content", ""))

    written: list[str] = []
    for filename, contents in grouped.items():
        contents = [c for c in contents if c.strip()]
        if not contents:
            continue
        changed = _merge_one_file(
            filename, contents, identity_dir / filename, client=client
        )
        if changed:
            written.append(filename)
    return written


def _clear_staging(staging_dir: Path) -> None:
    """shutil.rmtree 清空整个 .staging_skills/ 沙盒."""
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
        logger.info("Cleared staging dir: %s", staging_dir)


def _read_staged_patches(staging_dir: Path, fallback) -> list[dict[str, str]]:
    """
    优先读 .staging_skills/identity_patches.json, 否则用 decision 里的 patches.
    一律规整为 [{target, content}] (兼容字符串 / FilePatch).
    """
    import json

    path = staging_dir / "identity_patches.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return normalize_patches(data.get("patches", []))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read staged patches (%s), using fallback.", exc)
    return normalize_patches(fallback)


# --------------------------------------------------------------------------- #
# Human-in-the-Loop 循环
# --------------------------------------------------------------------------- #

PROMPT = "操作指令: [Y]确认挂载并生效 | [N]丢弃清理 | [其他文本]提交修改意见进行重构: "


def _interaction_loop(
    decision: GatewayDecision,
    staging: StagingResult | None,
    *,
    staging_dir: Path,
    live_skills_dir: Path,
    identity_path: Path,
    forge_client: LLMClient,
    identity_client: LLMClient | None,
    input_fn: InputFn,
) -> CycleResult:
    sg = decision.skill_generation
    has_skill = staging is not None and sg.action in ("merge", "upgrade")
    compile_instruction = sg.compile_instruction
    current = staging

    while True:
        _print_report(decision, current, _read_staged_patches(staging_dir, decision.identity_update.patches))

        try:
            raw = input_fn(PROMPT)
        except (EOFError, KeyboardInterrupt):
            logger.warning("Interactive input aborted; leaving staging intact.")
            return CycleResult("aborted", "no input")

        choice = raw.strip()
        upper = choice.upper()

        if upper == "Y":
            patches = _read_staged_patches(staging_dir, decision.identity_update.patches)
            mounted_to = None

            if has_skill and current is not None:
                target = live_skills_dir / current.skill_dir.name
                if target.exists():
                    logger.error("Mount target already exists: %s", target)
                    print(f"❌ 挂载失败：正式目录已存在同名技能，拒绝覆盖: {target}")
                    # 不清理, 让用户处理后重试
                    continue

            try:
                written = _apply_identity_updates(
                    patches, identity_dir=identity_path.parent, client=identity_client
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Identity update failed: %s", exc, exc_info=True)
                print(f"❌ 身份文件写入失败，沙盒已保留：{exc}")
                return CycleResult("error", str(exc))

            try:
                if has_skill and current is not None:
                    mounted_to = _mount_skill(current.skill_dir, live_skills_dir)
            except Exception as exc:  # noqa: BLE001
                logger.error("Mount failed: %s", exc, exc_info=True)
                print(f"❌ 挂载失败，沙盒已保留：{exc}")
                # 此时身份文件可能已经写入, 不清理沙盒, 方便人工检查后重试
                continue
            _clear_staging(staging_dir)
            bits = []
            if mounted_to:
                bits.append(str(mounted_to))
            if written:
                bits.append("身份文件: " + ", ".join(written))
            detail = " | ".join(bits) if bits else "identity-only"
            print(f"✅ 已挂载并生效。{detail}")
            return CycleResult("mounted", detail)

        if upper == "N":
            _clear_staging(staging_dir)
            print("🗑️ 已清理沙盒，本周期不做任何变更。")
            return CycleResult("discarded")

        # 其他文本 -> 修改意见, 回炉重构 (仅对技能代码有意义)
        if not has_skill:
            print("（本周期无技能可重构，请输入 Y 确认身份更新或 N 丢弃。）")
            continue

        feedback = choice
        print("🔧 正在回炉重构...")
        compile_instruction = (
            f"{compile_instruction}\n\n# 用户追加修改意见\n{feedback}"
        )
        logger.info("Refining skill %s with feedback: %s", sg.target_name, feedback)
        try:
            current = generate_skill_to_staging(
                sg.target_name,
                compile_instruction,
                client=forge_client,
                staging_dir=staging_dir,
                overwrite=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Refine failed: %s", exc)
            print(f"❌ 重构失败：{exc}")
            return CycleResult("error", str(exc))
        # 循环回到顶部, 重新打印报告 + 弹确认


# --------------------------------------------------------------------------- #
# 主工作流
# --------------------------------------------------------------------------- #


def run_satellite_cycle(
    *,
    hours: int = DEFAULT_HOURS,
    source: str = "markdown",
    memory_dir: Path | str = DEFAULT_MEMORY_DIR,
    db_path: Path | str | None = None,
    table: str = "interaction_logs",
    gateway_client: LLMClient | None = None,
    forge_client: LLMClient | None = None,
    identity_client: LLMClient | None = None,
    staging_dir: Path | str = DEFAULT_STAGING_DIR,
    live_skills_dir: Path | str = LIVE_SKILLS_DIR,
    identity_path: Path | str = DEFAULT_IDENTITY_PATH,
    input_fn: InputFn = input,
) -> CycleResult:
    """
    执行一个完整的 Satellite 周期. 返回 CycleResult.

    数据源默认 markdown (直读 memory/); 客户端默认惰性创建 OpenAIClient
    (需 OPENAI_API_KEY); 测试可注入 mock. input_fn 默认 builtins.input.
    """
    staging_dir = Path(staging_dir)
    live_skills_dir = Path(live_skills_dir)
    identity_path = Path(identity_path)

    # ---- 第一步: 嗅探 ----
    src_desc = str(memory_dir) if source == "markdown" else str(db_path)
    logger.info("Step 1/4 — sniffing logs (last %dh, source=%s) from %s", hours, source, src_desc)
    try:
        sniff_kwargs: dict = {"hours": hours, "source": source, "memory_dir": memory_dir}
        if db_path is not None:
            sniff_kwargs["db_path"] = db_path
            sniff_kwargs["table"] = table
        result = sniff(**sniff_kwargs)
    except DatabaseConnectionError as exc:
        logger.info("No log database to sniff (%s). Nothing to do.", exc)
        return CycleResult("no_logs", str(exc))
    except LogSnifferError as exc:
        logger.error("Sniff failed: %s", exc)
        return CycleResult("error", str(exc))

    if not result.cleaned:
        logger.info("No valid logs in the window. Exiting cycle.")
        return CycleResult("no_logs", "empty window")
    logger.info("Sniffed %d row(s), %d cleaned.", result.fetched, len(result.cleaned))

    # ---- 第二步: 研判 (附带现有技能清单做去重) ----
    logger.info("Step 2/4 — evaluating habits via gateway (with dedup catalog).")
    if gateway_client is None:
        gateway_client = make_llm_client(json_mode=True)
    try:
        catalog = build_skill_catalog([SkillRoot(live_skills_dir, "user")])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build skill catalog: %s", exc)
        catalog = ""
    try:
        decision = evaluate_habits(
            result.json, client=gateway_client, extra_user_context=catalog
        )
    except LLMResponseError as exc:
        logger.error("Gateway evaluation failed: %s", exc)
        return CycleResult("error", str(exc))

    sg, iu = decision.skill_generation, decision.identity_update
    logger.info("Decision: skill=%s identity=%s", sg.action, iu.action)
    if sg.action == "ignore" and iu.action == "ignore":
        logger.info("Both skill_generation and identity_update are 'ignore'. Silent exit.")
        return CycleResult("ignored", "nothing actionable")

    # ---- 第三步: 暂存 ----
    logger.info("Step 3/4 — staging artifacts.")
    if forge_client is None:
        forge_client = make_llm_client(json_mode=False)

    staging_result: StagingResult | None = None
    if sg.action in ("merge", "upgrade"):
        staging_result = generate_skill_to_staging(
            sg.target_name,
            sg.compile_instruction,
            client=forge_client,
            staging_dir=staging_dir,
            overwrite=True,
        )
    if iu.action == "update" and iu.patches:
        stage_identity_update(iu.patches, staging_dir=staging_dir)

    # ---- 第四步: 推送 + 挂载 ----
    logger.info("Step 4/4 — human-in-the-loop confirmation.")
    return _interaction_loop(
        decision,
        staging_result,
        staging_dir=staging_dir,
        live_skills_dir=live_skills_dir,
        identity_path=identity_path,
        forge_client=forge_client,
        identity_client=identity_client,
        input_fn=input_fn,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="MetaSkill Phase 4 — Satellite main cycle.")
    p.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    p.add_argument("--source", choices=["markdown", "sqlite"], default="markdown")
    p.add_argument("--memory", default=str(DEFAULT_MEMORY_DIR))
    p.add_argument("--db", default=None, help="SQLite path (only for --source sqlite)")
    p.add_argument("--table", default="interaction_logs")
    p.add_argument(
        "--provider",
        default=None,
        help="LLM provider: deepseek | openclaw | openai (默认读 env SATELLITE_LLM_PROVIDER, 再默认 deepseek)",
    )
    p.add_argument("--model", default=None, help="覆盖模型名 (默认按 provider 预设, deepseek 为 deepseek-v4-pro)")
    p.add_argument("--staging", default=str(DEFAULT_STAGING_DIR))
    p.add_argument("--skills-dir", default=str(LIVE_SKILLS_DIR))
    p.add_argument("--identity", default=str(DEFAULT_IDENTITY_PATH))
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        # 策略研判走 JSON 模式; 代码生成与身份合并走纯文本模式.
        gateway_client = make_llm_client(
            json_mode=True, provider=args.provider, model=args.model
        )
        text_client = make_llm_client(
            json_mode=False, provider=args.provider, model=args.model
        )
    except RuntimeError as exc:
        logger.error("LLM client init failed: %s", exc)
        print(f"❌ 无法初始化 LLM 客户端：{exc}")
        return 2

    result = run_satellite_cycle(
        hours=args.hours,
        source=args.source,
        memory_dir=args.memory,
        db_path=args.db,
        table=args.table,
        gateway_client=gateway_client,
        forge_client=text_client,
        identity_client=text_client,
        staging_dir=args.staging,
        live_skills_dir=args.skills_dir,
        identity_path=args.identity,
    )
    logger.info("Cycle finished: %s", result)
    return 0 if result.status in ("mounted", "discarded", "ignored", "no_logs") else 1


if __name__ == "__main__":
    raise SystemExit(main())
