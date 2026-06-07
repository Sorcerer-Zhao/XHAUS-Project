#!/usr/bin/env python3
"""
Send OpenClaw call popup to iPhone via Pushcut.

Lock screen & unlocked: notification body = script, action buttons Cancel / Call.
Requires Pushcut app + notification template「OpenClaw预约」— see references/pushcut-popup-setup.md
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".openclaw" / "phone-call-config.json"
DEFAULT_NOTIFICATION = "OpenClaw预约"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def send_pushcut_popup(
    *,
    script: str,
    tel: str,
    title: str = "📞 OpenClaw 预约",
    notification_name: str | None = None,
    api_key: str | None = None,
    dry_run: bool = False,
    delay: str | None = None,
) -> dict:
    cfg = load_config()
    pushcut = cfg.get("pushcut", {})
    api_key = api_key or pushcut.get("api_key", "")
    notification_name = notification_name or pushcut.get("notification_name", DEFAULT_NOTIFICATION)

    if not api_key:
        return {
            "success": False,
            "error": "Missing Pushcut API key",
            "config_help": {
                "file": str(CONFIG_PATH),
                "format": {
                    "pushcut": {
                        "api_key": "your-api-key",
                        "notification_name": "OpenClaw预约",
                    }
                },
            },
        }

    payload = {
        "id": f"openclaw-call-{hash(script + tel) & 0xFFFFFFFF:08x}",
        "title": title,
        "text": script,
        "isTimeSensitive": True,
        "sound": "subtle",
        "actions": [
            {"name": "Cancel"},
            {
                "name": "Call",
                "url": tel if tel.startswith("tel:") else f"tel:{tel}",
            },
        ],
    }
    if delay:
        payload["delay"] = delay

    url = f"https://api.pushcut.io/v1/notifications/{notification_name}?api_key={api_key}"

    if dry_run:
        return {"success": True, "dry_run": True, "url": url, "payload": payload}

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            return {"success": True, "response": body, "payload": payload}
    except urllib.error.HTTPError as e:
        return {
            "success": False,
            "error": f"HTTP {e.code}",
            "detail": e.read().decode(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Send Pushcut call popup to iPhone")
    parser.add_argument("--script", required=True)
    parser.add_argument("--tel", required=True, help="tel:+86... or +86...")
    parser.add_argument("--title", default="📞 OpenClaw 预约")
    parser.add_argument("--delay", help="Pushcut delay e.g. 10m (needs Pushcut Server Extended)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tel = args.tel if args.tel.startswith("tel:") else f"tel:{args.tel}"
    result = send_pushcut_popup(
        script=args.script,
        tel=tel,
        title=args.title,
        dry_run=args.dry_run,
        delay=args.delay,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
