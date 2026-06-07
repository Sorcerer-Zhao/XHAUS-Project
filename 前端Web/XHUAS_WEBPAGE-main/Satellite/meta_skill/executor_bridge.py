"""
executor_bridge.py — MetaSkill 阶段三: 执行层 (生成手脚)

把网关层的 `GatewayDecision` 落地为 `.staging_skills/` 沙盒里的真实技能:

  步骤 A  脚手架生成 : subprocess 调用原厂 init_skill.py 生成标准骨架 (SKILL.md),
                       并补写 manifest.json (init_skill.py 本身不产出 manifest).
  步骤 B  核心代码补全: 调用项目通用 LLM (gateway_router.OpenAIClient),
                       把 compile_instruction 投喂给它, 生成并覆写 executor.py.
  步骤 C  质量关卡    : (C-1) from quick_validate import validate_skill 校验 SKILL.md;
                       (C-2) py_compile 编译生成的 executor.py, 失败则自愈重生一次.
                       两关都过才算 StagingResult.passed == True.

另外提供 stage_identity_update(patches): 把身份补丁暂存到
`.staging_skills/identity_patches.json`, 供阶段四挂载使用.

注意
----
- 原厂 init_skill.py 的 argparse: 位置参数 skill_name; --path (必填);
  --resources scripts,references,assets; --examples. 它只生成 SKILL.md,
  不生成 manifest.json, 因此 manifest 由本模块补写.
- quick_validate.validate_skill(path) 返回 (bool, str), 按元组解包.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# 暴力导入原厂 skill-creator 脚本路径 (按需求显式 append)
# --------------------------------------------------------------------------- #

SKILL_CREATOR_SCRIPTS = (
    "/opt/homebrew/lib/node_modules/openclaw/skills/skill-creator/scripts/"
)
if SKILL_CREATOR_SCRIPTS not in sys.path:
    sys.path.append(SKILL_CREATOR_SCRIPTS)

try:  # 原厂质检函数: validate_skill(path) -> (bool, str)
    from quick_validate import validate_skill  # type: ignore
except ImportError:  # pragma: no cover
    validate_skill = None  # type: ignore[assignment]

try:  # 仅用于复算 init_skill 归一化后的目录名
    from init_skill import normalize_skill_name  # type: ignore
except ImportError:  # pragma: no cover

    def normalize_skill_name(name: str) -> str:  # type: ignore[misc]
        import re

        n = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        return re.sub(r"-{2,}", "-", n)


# 复用阶段二的"项目通用 LLM API"
from gateway_router import LLMClient, OpenAIClient  # noqa: E402

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 路径常量
# --------------------------------------------------------------------------- #

PROJECT_ROOT: Path = Path(__file__).resolve().parent  # skills/Satellite
DEFAULT_STAGING_DIR: Path = PROJECT_ROOT / ".staging_skills"
INIT_SKILL_PY: Path = Path(SKILL_CREATOR_SCRIPTS) / "init_skill.py"
IDENTITY_PATCH_FILE = "identity_patches.json"


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class ExecutorBridgeError(Exception):
    """executor_bridge 顶层异常."""


class ScaffoldError(ExecutorBridgeError):
    """init_skill.py 脚手架生成失败."""


class CodeGenerationError(ExecutorBridgeError):
    """LLM 生成 executor.py 失败."""


# --------------------------------------------------------------------------- #
# Skill Compiler System Prompt (代码生成)
# --------------------------------------------------------------------------- #

SKILL_COMPILER_SYSTEM_PROMPT = """\
你是 Skill Compiler, MetaSkill 执行层的代码编译器.
根据给定的 compile_instruction, 产出一个完整、可直接运行的 Python 模块,
它将被写入某个 Skill 的 executor.py.

硬性要求:
- 只输出 Python 源码本身, 不要任何 Markdown 围栏 (```), 不要解释性文字.
- 顶部包含 module docstring, 说明该 Skill 的用途.
- 实现一个清晰的入口函数 run(...) 作为该技能的主执行函数.
- 使用规范的 type hints 与必要的异常处理.
- 不依赖未在标准库中的包; 如必须依赖第三方, 用 try/except ImportError 给出友好提示.
- 代码必须能通过 `python -m py_compile` 编译.
"""


# --------------------------------------------------------------------------- #
# 结果对象
# --------------------------------------------------------------------------- #


@dataclass
class StagingResult:
    target_name: str
    skill_dir: Path
    skill_md: Path
    manifest: Path
    executor: Path
    valid: bool  # 原厂 quick_validate (SKILL.md 字段合规)
    validation_message: str
    compiled: bool = False  # py_compile 通过 (executor.py 语法可编译)
    compile_message: str = ""
    files: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """质量关卡总判定: 原厂质检 + 编译检测 双通过."""
        return self.valid and self.compiled

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "skill_dir": str(self.skill_dir),
            "valid": self.valid,
            "validation_message": self.validation_message,
            "compiled": self.compiled,
            "compile_message": self.compile_message,
            "passed": self.passed,
            "files": self.files,
        }


# --------------------------------------------------------------------------- #
# 内部步骤
# --------------------------------------------------------------------------- #


def _scaffold(target_name: str, staging_dir: Path, *, overwrite: bool) -> Path:
    """步骤 A: subprocess 调 init_skill.py, 返回生成的 skill 目录."""
    normalized = normalize_skill_name(target_name)
    if not normalized:
        raise ScaffoldError(f"Invalid target_name: {target_name!r}")

    staging_dir.mkdir(parents=True, exist_ok=True)
    skill_dir = staging_dir / normalized

    if skill_dir.exists():
        if not overwrite:
            raise ScaffoldError(f"Skill dir already exists: {skill_dir}")
        # 仅清理 staging 沙盒内的目标目录, 防止误删
        if staging_dir not in skill_dir.parents:
            raise ScaffoldError("Refusing to remove dir outside staging sandbox.")
        logger.info("Overwrite enabled, removing existing %s", skill_dir)
        shutil.rmtree(skill_dir)

    if not INIT_SKILL_PY.exists():
        raise ScaffoldError(f"init_skill.py not found: {INIT_SKILL_PY}")

    cmd = [
        sys.executable,
        str(INIT_SKILL_PY),
        normalized,
        "--path",
        str(staging_dir),
        "--resources",
        "scripts",
    ]
    logger.info("Running scaffolder: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScaffoldError(
            f"init_skill.py failed (exit {proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    logger.debug("init_skill.py stdout:\n%s", proc.stdout)

    if not skill_dir.exists():
        raise ScaffoldError(
            f"Scaffold reported success but {skill_dir} missing. "
            f"stdout:\n{proc.stdout}"
        )
    return skill_dir


def _make_description(target_name: str, compile_instruction: str) -> str:
    """从 target_name + compile_instruction 合成一个合规的一行描述."""
    title = normalize_skill_name(target_name).replace("-", " ").strip()
    first = ""
    if compile_instruction.strip():
        first = compile_instruction.strip().splitlines()[0]
    text = f"{title}. {first}".strip()
    for ch in "<>[]":  # validator 禁止 <>; [] 会触发 YAML flow-sequence
        text = text.replace(ch, "")
    text = " ".join(text.split())  # 折叠空白/换行
    if not text:
        text = title or "metaskill generated skill"
    if len(text) > 1000:
        text = text[:997].rstrip() + "..."
    return text


def _finalize_skill_md(skill_dir: Path, target_name: str, description: str) -> None:
    """
    重写 SKILL.md 的 frontmatter, 把占位 description 换成合规字符串.

    原厂模板里 description 形如 `[TODO: ...]`, YAML 会解析成 list 导致质检失败,
    因此这里用双引号包裹 (兼容有/无 PyYAML 两种解析路径).
    """
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")
    lines = content.splitlines()

    body = ""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body = "\n".join(lines[i + 1 :])
                break

    name = normalize_skill_name(target_name)
    esc = description.replace("\\", "\\\\").replace('"', '\\"')
    front = f'---\nname: {name}\ndescription: "{esc}"\n---\n'
    if body and not body.startswith("\n"):
        body = "\n" + body
    skill_md.write_text(front + body + "\n", encoding="utf-8")
    logger.info("Finalized SKILL.md frontmatter for %s", name)


def _write_manifest(
    skill_dir: Path, target_name: str, description: str, compile_instruction: str
) -> Path:
    """补写 manifest.json (原厂 init_skill.py 不产出此文件)."""
    manifest = {
        "name": normalize_skill_name(target_name),
        "version": "0.1.0",
        "description": description,
        "entrypoint": "executor.py",
        "generated_by": "MetaSkill/executor_bridge",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "compile_instruction": compile_instruction,
        "status": "staged",
    }
    path = skill_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote manifest.json -> %s", path)
    return path


def _strip_code_fence(text: str) -> str:
    """去掉模型可能附带的 ```python ... ``` 围栏."""
    t = text.strip()
    if t.startswith("```"):
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -3]
    return t.strip() + "\n"


def _compile_check(path: Path) -> tuple[bool, str]:
    """
    步骤 C-2: 质量关卡 — 语法编译检测生成的 executor.py.

    用内置 compile(..., "exec") 做纯语法检查, **不**写入 .pyc / __pycache__,
    避免污染将被挂载的技能目录.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - 防御
        return False, f"cannot read executor: {exc}"
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        msg = f"{exc.msg} (line {exc.lineno}, offset {exc.offset})"
        logger.warning("Syntax check FAILED for %s: %s", path, msg)
        return False, msg
    except ValueError as exc:  # pragma: no cover - 例如源码含 NUL 字节
        logger.warning("Compile error for %s: %s", path, exc)
        return False, f"{type(exc).__name__}: {exc}"
    logger.info("Syntax check passed for %s", path)
    return True, "syntax OK"


def _generate_executor(
    skill_dir: Path,
    compile_instruction: str,
    client: LLMClient,
    *,
    max_fix_attempts: int = 1,
) -> tuple[Path, bool, str]:
    """
    步骤 B: 调 LLM 生成 executor.py 并覆写, 随后做 py_compile 质检.

    若编译失败, 最多自愈 `max_fix_attempts` 次: 把编译错误回喂给模型让其修正.
    返回 (路径, 是否编译通过, 编译信息).
    """
    base_user = (
        "请根据以下 compile_instruction 生成该 Skill 的 executor.py 完整源码:\n\n"
        f"<COMPILE_INSTRUCTION>\n{compile_instruction}\n</COMPILE_INSTRUCTION>"
    )
    path = skill_dir / "executor.py"

    user = base_user
    compiled, message = False, ""
    for attempt in range(max_fix_attempts + 1):
        try:
            raw = client.complete(system=SKILL_COMPILER_SYSTEM_PROMPT, user=user)
        except Exception as exc:  # noqa: BLE001
            raise CodeGenerationError(f"LLM call failed: {exc}") from exc

        code = _strip_code_fence(raw)
        if not code.strip():
            raise CodeGenerationError("LLM returned empty executor code.")

        path.write_text(code, encoding="utf-8")
        logger.info(
            "Wrote executor.py (%d bytes, attempt %d) -> %s", len(code), attempt + 1, path
        )

        compiled, message = _compile_check(path)
        if compiled:
            return path, compiled, message

        if attempt < max_fix_attempts:
            logger.info("Self-heal: re-prompting LLM to fix compile error (attempt %d).", attempt + 1)
            user = (
                base_user
                + "\n\n# 你上一次生成的代码无法通过 python -m py_compile, 报错如下:\n"
                + f"{message}\n\n"
                + "## 上次代码\n" + code + "\n\n"
                + "请修正语法/缩进错误, 重新输出**完整**的 executor.py 源码 (仅源码, 无围栏)."
            )

    return path, compiled, message


def _validate(skill_dir: Path) -> tuple[bool, str]:
    """步骤 C: 原厂质检. validate_skill 返回 (bool, str)."""
    if validate_skill is None:
        msg = "quick_validate.validate_skill unavailable; skipping validation."
        logger.warning(msg)
        return False, msg
    try:
        valid, message = validate_skill(str(skill_dir))
    except Exception as exc:  # noqa: BLE001
        logger.warning("validate_skill raised %s: %s", type(exc).__name__, exc)
        return False, f"validator error: {exc}"

    if not valid:
        logger.warning("Skill validation FAILED for %s: %s", skill_dir, message)
    else:
        logger.info("Skill validation passed for %s: %s", skill_dir, message)
    return valid, message


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def generate_skill_to_staging(
    target_name: str,
    compile_instruction: str,
    *,
    client: LLMClient | None = None,
    staging_dir: Path | str = DEFAULT_STAGING_DIR,
    overwrite: bool = True,
) -> StagingResult:
    """
    在 `.staging_skills/{target_name}/` 沙盒中生成完整技能.

    步骤 A 脚手架 -> 步骤 B LLM 写 executor.py -> 步骤 C 原厂质检.

    参数
    ----
    target_name: str
        目标 Skill 名 (内部按 init_skill 规则归一化为 hyphen-case).
    compile_instruction: str
        给 Skill Compiler 的详细编译指令.
    client: LLMClient | None
        LLM 客户端, 默认 OpenAIClient; 测试可注入 mock.
    staging_dir: Path | str
        沙盒根目录, 默认项目根的 .staging_skills/.
    overwrite: bool
        目标目录已存在时是否清理重建 (仅限沙盒内).
    """
    staging_dir = Path(staging_dir)
    if client is None:
        client = OpenAIClient()

    skill_dir = _scaffold(target_name, staging_dir, overwrite=overwrite)
    description = _make_description(target_name, compile_instruction)
    _finalize_skill_md(skill_dir, target_name, description)
    manifest = _write_manifest(skill_dir, target_name, description, compile_instruction)
    executor, compiled, compile_message = _generate_executor(
        skill_dir, compile_instruction, client
    )
    valid, message = _validate(skill_dir)

    files = sorted(
        str(p.relative_to(skill_dir)) for p in skill_dir.rglob("*") if p.is_file()
    )
    result = StagingResult(
        target_name=normalize_skill_name(target_name),
        skill_dir=skill_dir,
        skill_md=skill_dir / "SKILL.md",
        manifest=manifest,
        executor=executor,
        valid=valid,
        validation_message=message,
        compiled=compiled,
        compile_message=compile_message,
        files=files,
    )
    logger.info(
        "Quality gate for %s: validate=%s compile=%s (passed=%s)",
        result.target_name, valid, compiled, result.passed,
    )
    return result


_VALID_TARGETS = ("IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md")


def normalize_patches(patches: Any) -> list[dict[str, str]]:
    """
    把异构补丁规整为 [{target, content}] 列表.

    支持的单项形态:
      - 纯字符串                  -> {target:"IDENTITY.md", content:str}
      - {"target":..,"content":..} -> 原样 (target 非法时回退 IDENTITY.md)
      - 带 .target/.content 属性的对象 (如 Pydantic FilePatch)
    自动去空、去重 (按 (target, content)).
    """
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in patches or []:
        if isinstance(item, str):
            target, content = "IDENTITY.md", item
        elif isinstance(item, dict):
            target = str(item.get("target") or "IDENTITY.md")
            content = str(item.get("content") or "")
        else:
            target = str(getattr(item, "target", "IDENTITY.md"))
            content = str(getattr(item, "content", ""))
        content = content.strip()
        if not content:
            continue
        if target not in _VALID_TARGETS:
            target = "IDENTITY.md"
        key = (target, content)
        if key not in seen:
            seen.add(key)
            out.append({"target": target, "content": content})
    return out


def stage_identity_update(
    patches: Any,
    *,
    staging_dir: Path | str = DEFAULT_STAGING_DIR,
) -> Path | None:
    """
    把带文件路由的身份/认知补丁暂存到 `.staging_skills/identity_patches.json`.

    patches 可为字符串 / {target,content} / FilePatch 的混合列表.
    无有效 patches 时返回 None, 不落盘.
    """
    cleaned = normalize_patches(patches)
    if not cleaned:
        logger.info("No identity patches to stage.")
        return None

    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    path = staging_dir / IDENTITY_PATCH_FILE

    existing: list[dict[str, str]] = []
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            existing = normalize_patches(prev.get("patches", []))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read existing patches, overwriting: %s", exc)

    merged = normalize_patches([*existing, *cleaned])
    target_files = sorted({p["target"] for p in merged})

    payload = {
        "patches": merged,
        "target_files": target_files,
        "staged_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Staged %d identity patch(es) -> %s (targets=%s)", len(merged), path, target_files)
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="MetaSkill Phase 3 — executor bridge.")
    p.add_argument("target_name", help="Skill name to scaffold into .staging_skills/")
    p.add_argument("--instruction", required=True, help="compile_instruction for Skill Compiler")
    p.add_argument("--staging", default=str(DEFAULT_STAGING_DIR))
    p.add_argument("--model", default="gpt-4o-mini")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    result = generate_skill_to_staging(
        args.target_name,
        args.instruction,
        client=OpenAIClient(model=args.model),
        staging_dir=args.staging,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
