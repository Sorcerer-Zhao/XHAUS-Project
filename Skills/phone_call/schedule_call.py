#!/usr/bin/env python3
"""
定时预约：写入 ~/Desktop/Openclaw-PhoneCall/{时间}.json，可选 AirDrop 到 iPhone。
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apple_reservation_sync import sync_reservation_to_apple
from bundle_transfer import (
    DESKTOP_BUNDLE_DIR,
    airdrop_reservation,
    build_bundle,
    write_reservation_json,
)

SKILL_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SKILL_DIR.parent
PHONE_CALLS_PATH = WORKSPACE_ROOT / "memory" / "phone-calls.json"
TZ = timezone(timedelta(hours=8))


def normalize_phone(raw: str) -> str:
    raw = raw.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if raw.startswith("+"):
        return raw
    if raw.startswith("0086"):
        return "+86" + raw[4:]
    if raw.startswith("1") and len(raw) == 11:
        return "+86" + raw
    return raw


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    return text.strip("-")[:40] or "call"


def parse_call_at(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def load_phone_calls() -> dict:
    if PHONE_CALLS_PATH.exists():
        return json.loads(PHONE_CALLS_PATH.read_text(encoding="utf-8"))
    return {"entries": []}


def save_phone_calls(data: dict) -> None:
    PHONE_CALLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PHONE_CALLS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cleanup_old_entries(data: dict, days: int = 14) -> None:
    cutoff = datetime.now(TZ) - timedelta(days=days)
    kept = []
    for entry in data.get("entries", []):
        call_at = entry.get("callAt", "")
        try:
            dt = parse_call_at(call_at)
            if dt >= cutoff or entry.get("status") == "scheduled":
                kept.append(entry)
        except ValueError:
            kept.append(entry)
    data["entries"] = kept


def main():
    parser = argparse.ArgumentParser(description="Schedule phone call via reservation JSON")
    parser.add_argument("--to", required=True)
    parser.add_argument("--call-at", required=True, help="ISO-8601, e.g. 2026-06-07T10:00:00+08:00")
    parser.add_argument("--title", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--meal-at", help="用餐时间 ISO-8601，写入 iCloud 日历")
    parser.add_argument("--location", default="", help="用餐地点，写入日历")
    parser.add_argument("--meal-duration-hours", type=float, default=2.0)
    parser.add_argument("--calendar", default="个人", help="目标日历名称，默认 iCloud「个人」")
    parser.add_argument("--skip-contact", action="store_true")
    parser.add_argument("--skip-calendar", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--airdrop", action="store_true", help="AirDrop the new json to iPhone")
    args = parser.parse_args()

    to = normalize_phone(args.to)
    call_at = parse_call_at(args.call_at)
    meal_at = parse_call_at(args.meal_at) if args.meal_at else None
    now = datetime.now(TZ)

    if call_at <= now and not args.dry_run:
        print(json.dumps({
            "success": False,
            "error": "call-at must be in the future",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    entry_id = f"{call_at.strftime('%Y-%m-%d')}-{slugify(args.title)}"
    payload = {
        "id": entry_id,
        "title": args.title,
        "phone": to,
        "to": to,
        "tel": f"tel:{to}",
        "script": args.script,
        "callAt": call_at.isoformat(),
        "completed": False,
    }
    if meal_at:
        payload["mealAt"] = meal_at.isoformat()
    if args.location:
        payload["location"] = args.location.strip()

    entry = {
        **payload,
        "status": "scheduled",
        "createdAt": now.isoformat(),
        "jsonFile": None,
        "appleSync": None,
    }

    json_path = None
    airdrop_result = None
    apple_sync = sync_reservation_to_apple(
        title=args.title,
        phone=to,
        script=args.script,
        meal_at=meal_at,
        location=args.location,
        meal_duration_hours=args.meal_duration_hours,
        calendar_name=args.calendar,
        skip_contact=args.skip_contact,
        skip_calendar=args.skip_calendar,
        dry_run=args.dry_run,
    )
    entry["appleSync"] = apple_sync

    if args.dry_run:
        bundle_result = {"dry_run": True, "would_write": str(DESKTOP_BUNDLE_DIR / f"{call_at.strftime('%Y-%m-%d_%H-%M-%S')}.json")}
    else:
        build_bundle(open_finder=False)
        json_path = write_reservation_json(payload, call_at)
        entry["jsonFile"] = json_path.name
        bundle_result = {"ok": True, "json": str(json_path), "bundle_dir": str(DESKTOP_BUNDLE_DIR)}
        if args.airdrop:
            airdrop_result = airdrop_reservation(json_path)

        data = load_phone_calls()
        cleanup_old_entries(data)
        data["entries"] = [e for e in data.get("entries", []) if e.get("id") != entry_id]
        data["entries"].append(entry)
        save_phone_calls(data)

    print(json.dumps({
        "success": True,
        "dry_run": args.dry_run,
        "entry": entry,
        "bundle": bundle_result,
        "airdrop": airdrop_result,
        "apple_sync": apple_sync,
        "shortcut": "预约拨号v2.0",
        "iphone_sync": (
            "AirDrop Mac 桌面 Openclaw-PhoneCall/current.json 到 iPhone "
            "我的 iPhone/Shortcuts/ 覆盖。"
        ),
        "at_call_time": (
            f"到 {call_at.strftime('%H:%M')} 在 iPhone 运行「预约拨号v2.0」弹窗拨号。"
        ),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
