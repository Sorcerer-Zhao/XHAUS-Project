#!/usr/bin/env python3
"""
Initiate a phone call on macOS via tel: URL (requires iPhone Cellular Calls).
The user speaks during the call; this script only triggers dialing.
"""

import argparse
import json
import subprocess
import sys


def normalize_phone(raw: str) -> str:
    raw = raw.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if raw.startswith("+"):
        return raw
    if raw.startswith("0086"):
        return "+86" + raw[4:]
    if raw.startswith("1") and len(raw) == 11:
        return "+86" + raw
    return raw


def main():
    parser = argparse.ArgumentParser(description="Trigger phone dial via macOS tel: URL")
    parser.add_argument("--to", required=True, help="Destination phone number")
    parser.add_argument("--dry-run", action="store_true", help="Preview without dialing")
    args = parser.parse_args()

    to = normalize_phone(args.to)
    tel_url = f"tel:{to}"

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "to": to,
            "tel_url": tel_url,
            "note": "Would run: open tel:... (user must confirm on macOS)",
        }, ensure_ascii=False, indent=2))
        return

    try:
        subprocess.run(["open", tel_url], check=True)
    except FileNotFoundError:
        print(json.dumps({
            "success": False,
            "error": "open command not found (macOS only)",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps({
        "success": True,
        "action": "dial_initiated",
        "to": to,
        "note": "Dial prompt shown on Mac; call routes via iPhone if configured.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
