#!/usr/bin/env python3
"""
在 XHAUS 项目根目录运行，引导安装本地 Skill 到 ~/.xhaus/skills。

  cd /path/to/XHAUS
  python3 install_skill.py

也可传入目录跳过引导：
  python3 install_skill.py ~/projects/my-skill
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from xhaus.cli.install_skill_wizard import run_install_skill_wizard  # noqa: E402
from xhaus.skills.install_local import (  # noqa: E402
    cloud_skill_instructions,
    install_local_skill,
    is_cloud_skill_reference,
    validate_local_skill_dir,
)
from xhaus.skills.paths import default_skills_root


def _install_direct(
    source: Path,
    *,
    force: bool,
    no_restart: bool,
    no_relink: bool,
) -> int:
    print()
    print(f"  来源: {source}")
    print(f"  共享: {default_skills_root()}")
    print()

    result = install_local_skill(
        source,
        force=force,
        relink_agents=not no_relink,
        restart_gateway=not no_restart,
    )

    mark = "OK" if result.ok else "ERR"
    print(f"  {mark} {result.message}")
    if result.dest:
        print(f"  - 路径: {result.dest}")
    for note in result.warnings or []:
        print(f"  - {note}")
    for err in result.errors or []:
        print(f"  WARN {err}", file=sys.stderr)
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="XHAUS 本地 Skill 安装向导（复制到 ~/.xhaus/skills）",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="本地 skill 目录；省略则进入 CLI 引导",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同名 skill")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--no-relink", action="store_true")
    parser.add_argument("--cloud-help", action="store_true")
    args = parser.parse_args()

    if args.cloud_help:
        print(cloud_skill_instructions())
        return 0

    if not args.source:
        return run_install_skill_wizard()

    raw = args.source.strip()
    if is_cloud_skill_reference(raw):
        print(cloud_skill_instructions())
        return 1

    source, errors = validate_local_skill_dir(Path(raw))
    if errors:
        for err in errors:
            print(f"  ERR {err}", file=sys.stderr)
        return 1

    return _install_direct(
        source,
        force=args.force,
        no_restart=args.no_restart,
        no_relink=args.no_relink,
    )


if __name__ == "__main__":
    raise SystemExit(main())
