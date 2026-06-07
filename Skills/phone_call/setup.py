#!/usr/bin/env python3
"""首次配置：创建 ~/Desktop/Openclaw-PhoneCall 并 AirDrop 到 iPhone。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bundle_transfer import (
    DESKTOP_BUNDLE_DIR,
    SHORTCUT_FILE_NAME,
    airdrop_folder,
    airdrop_reservation,
    build_and_airdrop_folder,
    build_bundle,
    list_reservation_jsons,
)
from shortcut_builder import (
    BUNDLE_FOLDER_NAME,
    CURRENT_JSON_NAME,
    IPHONE_DATA_FOLDER,
    IPHONE_JSON_LOCATION_HINT,
    SHORTCUT_NAME,
)

SETUP_MARKER = Path.home() / ".openclaw" / "phone-call-setup.json"
TZ = timezone(timedelta(hours=8))
SETUP_VERSION = 6

ONBOARDING_STEPS = (
    "run_setup",
    "mac_bundle",
    "iphone_shortcuts_folder",
    "iphone_install",
    "final",
)

STEP_HINTS = {
    "run_setup": (
        f"在 Mac 创建桌面文件夹 {BUNDLE_FOLDER_NAME}："
        f"python setup.py --run --skip-airdrop"
    ),
    "mac_bundle": (
        f"确认 Mac 桌面已有 {BUNDLE_FOLDER_NAME}，然后引导用户在 iPhone 建数据文件夹"
    ),
    "iphone_shortcuts_folder": (
        f"引导用户在 iPhone「文件」→ 我的 iPhone 下新建 **{IPHONE_DATA_FOLDER}** 文件夹，"
        f"用于存放 {CURRENT_JSON_NAME}"
    ),
    "iphone_install": (
        f"AirDrop {SHORTCUT_NAME}.shortcut 并添加快捷指令；"
        f"把 {CURRENT_JSON_NAME} 放入 我的 iPhone/{IPHONE_DATA_FOLDER}/"
    ),
    "final": (
        f"试运行「{SHORTCUT_NAME}」，确认能读到 "
        f"我的 iPhone/{IPHONE_DATA_FOLDER}/{CURRENT_JSON_NAME}"
    ),
    "done": "无需引导",
}


def now_iso() -> str:
    return datetime.now(TZ).isoformat()


def load_marker() -> dict:
    if SETUP_MARKER.exists():
        try:
            return json.loads(SETUP_MARKER.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_marker(data: dict) -> None:
    SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
    SETUP_MARKER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _migrate_marker(marker: dict) -> dict:
    if marker.get("setupVersion", 0) >= SETUP_VERSION:
        return marker
    steps = marker.setdefault("userConfirmedSteps", {})
    if marker.get("setupVersion", 0) < 6:
        # iPhone 数据目录 ShortcutData → Shortcuts，需重新确认 iPhone 侧文件夹
        steps.pop("iphone_shortcuts_folder", None)
        steps.pop("iphone_installed", None)
        marker["setupComplete"] = False
        if steps.get("final"):
            steps.pop("final", None)
    marker["setupVersion"] = SETUP_VERSION
    return marker


def check_status() -> dict:
    marker = load_marker()
    old_version = marker.get("setupVersion", 0)
    marker = _migrate_marker(marker)
    if marker.get("setupVersion", 0) != old_version:
        save_marker(marker)

    bundle_ok = DESKTOP_BUNDLE_DIR.is_dir() and (DESKTOP_BUNDLE_DIR / SHORTCUT_FILE_NAME).exists()
    steps = marker.get("userConfirmedSteps", {})
    step = _next_step(steps, bundle_ok)

    complete = step == "done"

    return {
        "setupComplete": complete,
        "needsOnboarding": not complete,
        "onboardingStep": step,
        "onboardingHint": STEP_HINTS.get(step, ""),
        "setupVersion": SETUP_VERSION,
        "checks": {
            "desktop_bundle": bundle_ok,
            "reservation_jsons": [p.name for p in list_reservation_jsons()],
            "marker_exists": SETUP_MARKER.exists(),
            "confirmed_steps": {k: v for k, v in steps.items() if v is True},
        },
        "paths": {
            "desktop_bundle_dir": str(DESKTOP_BUNDLE_DIR),
            "shortcut": str(DESKTOP_BUNDLE_DIR / SHORTCUT_FILE_NAME),
            "iphone_data_folder": IPHONE_DATA_FOLDER,
            "iphone_current_json": f"我的 iPhone/{IPHONE_DATA_FOLDER}/{CURRENT_JSON_NAME}",
            "iphone_folder_hint": IPHONE_JSON_LOCATION_HINT,
        },
    }


def _next_step(steps: dict, bundle_ok: bool) -> str:
    if not bundle_ok:
        return "run_setup"
    if not steps.get("mac_bundle"):
        return "mac_bundle"
    if not steps.get("iphone_shortcuts_folder"):
        return "iphone_shortcuts_folder"
    if not steps.get("iphone_installed"):
        return "iphone_install"
    if not steps.get("final"):
        return "final"
    return "done"


def run_setup(*, airdrop: bool) -> dict:
    marker = _migrate_marker(load_marker())
    marker.setdefault("userConfirmedSteps", {})
    marker["setupVersion"] = SETUP_VERSION
    marker["lastRunAt"] = now_iso()

    bundle = build_and_airdrop_folder() if airdrop else build_bundle(open_finder=True)

    if bundle.get("ok"):
        marker["userConfirmedSteps"]["mac_bundle"] = True
        marker["userConfirmedSteps"]["mac_bundle_at"] = now_iso()
    marker["infraReady"] = True
    marker["infraReadyAt"] = now_iso()
    save_marker(marker)

    return {"success": True, "bundle": bundle, "status": check_status()}


def mark_step(step: str) -> dict:
    if step not in ONBOARDING_STEPS:
        return {
            "error": f"unknown step: {step}",
            "valid_steps": list(ONBOARDING_STEPS),
        }
    marker = _migrate_marker(load_marker())
    marker.setdefault("userConfirmedSteps", {})
    marker["userConfirmedSteps"][step] = True
    marker["userConfirmedSteps"][f"{step}_at"] = now_iso()
    if step == "final":
        marker["setupComplete"] = True
        marker["setupCompletedAt"] = now_iso()
    save_marker(marker)
    return check_status()


def main():
    parser = argparse.ArgumentParser(description="Phone-call skill setup")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--run", action="store_true", help="Create Openclaw-PhoneCall folder + AirDrop")
    parser.add_argument("--airdrop", action="store_true", help="AirDrop folder or latest json (--latest-json)")
    parser.add_argument("--latest-json", action="store_true", help="With --airdrop, send newest reservation json")
    parser.add_argument("--skip-airdrop", action="store_true")
    parser.add_argument("--mark-step", metavar="STEP")
    args = parser.parse_args()

    if args.mark_step:
        print(json.dumps(mark_step(args.mark_step), ensure_ascii=False, indent=2))
        return

    if args.check_only:
        print(json.dumps(check_status(), ensure_ascii=False, indent=2))
        return

    if args.airdrop:
        if args.latest_json:
            jsons = list_reservation_jsons()
            if not jsons:
                result = {"ok": False, "error": "no reservation json in bundle folder"}
            else:
                result = airdrop_reservation(jsons[-1])
        else:
            result = airdrop_folder()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("ok") else 1)

    if args.run:
        result = run_setup(airdrop=not args.skip_airdrop)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
