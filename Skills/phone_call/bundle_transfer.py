"""
桌面文件夹 Openclaw-PhoneCall：快捷指令 + 按时间命名的预约 json。
每次预约写入 {YYYY-MM-DD_HH-MM-SS}.json，AirDrop 到 iPhone 同路径。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shortcut_builder import (
    BUNDLE_FOLDER_NAME,
    CURRENT_JSON_NAME,
    IPHONE_DATA_FOLDER,
    IPHONE_JSON_LOCATION_HINT,
    SHORTCUT_NAME,
    write_unsigned_shortcut,
)

SKILL_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SKILL_DIR / "assets"
DESKTOP_BUNDLE_DIR = Path.home() / "Desktop" / BUNDLE_FOLDER_NAME
SHORTCUT_FILE_NAME = "预约拨号v2.0.shortcut"
GUIDE_FILE_NAME = "iPhone安装指南.txt"
TZ = timezone(timedelta(hours=8))

BUNDLE_DIR = DESKTOP_BUNDLE_DIR


def reservation_filename(call_at: datetime) -> str:
    return call_at.strftime("%Y-%m-%d_%H-%M-%S") + ".json"


def normalize_payload(payload: dict) -> dict:
    out = dict(payload)
    if "phone" not in out and "to" in out:
        out["phone"] = out["to"]
    if "tel" not in out:
        out["tel"] = f"tel:{out.get('phone', '')}"
    if "completed" not in out:
        out["completed"] = False
    return out


def sync_current_json() -> Path | None:
    """把最早一条未完成预约写入 current.json（快捷指令只读此文件）。"""
    DESKTOP_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[str, dict]] = []
    for p in list_reservation_jsons():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("completed") is True:
            continue
        pending.append((p.name, data))
    current = DESKTOP_BUNDLE_DIR / CURRENT_JSON_NAME
    if not pending:
        if current.exists():
            current.unlink()
        return None
    pending.sort(key=lambda x: x[0])
    name, data = pending[0]
    payload = {**normalize_payload(data), "sourceFile": name, "completed": False}
    current.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def write_reservation_json(payload: dict, call_at: datetime) -> Path:
    """保存预约 json 到 ~/Desktop/Openclaw-PhoneCall/{时间}.json，并更新 current.json"""
    DESKTOP_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    data = normalize_payload(payload)
    data["completed"] = False
    path = DESKTOP_BUNDLE_DIR / reservation_filename(call_at)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_current_json()
    return path


def list_reservation_jsons() -> list[Path]:
    if not DESKTOP_BUNDLE_DIR.is_dir():
        return []
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.json$")
    return sorted(p for p in DESKTOP_BUNDLE_DIR.glob("*.json") if pat.match(p.name))


def _iphone_guide() -> str:
    return textwrap.dedent(f"""
    OpenClaw 电话预约 — Openclaw-PhoneCall 文件夹
    ============================================

    iPhone 数据路径（快捷指令读取）：
      {IPHONE_JSON_LOCATION_HINT}current.json

    首次安装
    --------
    1. 在 iPhone「文件」→ 我的 iPhone 下新建文件夹 {IPHONE_DATA_FOLDER}
    2. Mac AirDrop「预约拨号v2.0.shortcut」，添加快捷指令
    3. 将 current.json 放入 iPhone 的 {IPHONE_DATA_FOLDER} 文件夹

    每次预约
    --------
    Mac 更新桌面「{BUNDLE_FOLDER_NAME}」里的 current.json。
    只 AirDrop current.json 到 iPhone 的 {IPHONE_DATA_FOLDER}/ 覆盖即可。

    运行快捷指令
    ------------
    读 current.json → 弹出台词 → 菜单拨打/取消。
    到点由用户或 iOS 自动化运行快捷指令。
    """).strip()


def sign_shortcut(unsigned: Path, signed: Path) -> tuple[bool, str]:
    write_unsigned_shortcut(unsigned)
    sign = subprocess.run(
        ["shortcuts", "sign", "-i", str(unsigned), "-o", str(signed), "--mode", "anyone"],
        capture_output=True,
        text=True,
    )
    if sign.returncode != 0:
        return False, sign.stderr.strip() or sign.stdout.strip() or "shortcuts sign failed"
    return True, str(signed)


def build_bundle(*, open_finder: bool = True) -> dict:
    """首次/重建：文件夹 + 快捷指令 + 说明（不含预约 json）。"""
    DESKTOP_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    guide_path = DESKTOP_BUNDLE_DIR / GUIDE_FILE_NAME
    guide_path.write_text(_iphone_guide() + "\n", encoding="utf-8")

    unsigned = ASSETS_DIR / "openclaw-phone-call.shortcut"
    signed_assets = ASSETS_DIR / "openclaw-phone-call-signed.shortcut"
    signed_bundle = DESKTOP_BUNDLE_DIR / SHORTCUT_FILE_NAME

    ok, detail = sign_shortcut(unsigned, signed_assets)
    if not ok:
        return {"ok": False, "error": detail}

    shutil.copy2(signed_assets, signed_bundle)

    if open_finder:
        subprocess.run(["open", str(DESKTOP_BUNDLE_DIR)], check=False)

    return {
        "ok": True,
        "bundle_dir": str(DESKTOP_BUNDLE_DIR),
        "files": {
            "shortcut": str(signed_bundle),
            "guide": str(guide_path),
        },
        "shortcut_name": SHORTCUT_NAME,
        "built_at": datetime.now(TZ).isoformat(),
        "iphone_folder": IPHONE_DATA_FOLDER,
    }


def airdrop_path(path: Path) -> dict:
    if not path.exists():
        return {"ok": False, "error": f"not found: {path}"}
    subprocess.run(["open", "-a", "AirDrop", str(path)], check=False)
    return {"ok": True, "airdrop": True, "airdrop_path": str(path)}


def airdrop_folder() -> dict:
    built = build_bundle(open_finder=True)
    if not built.get("ok"):
        return built
    subprocess.run(["open", "-a", "AirDrop", str(DESKTOP_BUNDLE_DIR)], check=False)
    return {
        **built,
        "ok": True,
        "airdrop": True,
        "airdrop_target": str(DESKTOP_BUNDLE_DIR),
        "iphone_json_hint": IPHONE_JSON_LOCATION_HINT,
    }


def airdrop_current_json() -> dict:
    """只 AirDrop current.json（队首预约），覆盖 iPhone Shortcuts/ 里的同名文件。"""
    sync_current_json()
    current = DESKTOP_BUNDLE_DIR / CURRENT_JSON_NAME
    if not current.exists():
        return {"ok": False, "error": "no pending reservation; current.json not created"}
    subprocess.run(["open", "-a", "AirDrop", str(current)], check=False)
    return {
        "ok": True,
        "airdrop": True,
        "airdrop_file": str(current),
        "iphone_save_to": IPHONE_JSON_LOCATION_HINT,
        "note": (
            f"将 current.json 保存到 iPhone 我的 iPhone/{IPHONE_DATA_FOLDER}/，"
            f"覆盖旧文件；到点运行「{SHORTCUT_NAME}」。"
        ),
    }


def airdrop_reservation(json_path: Path | None = None) -> dict:
    """预约后 AirDrop：仅 current.json（忽略单独的时间戳 json）。"""
    if json_path is not None and not json_path.exists():
        return {"ok": False, "error": f"not found: {json_path}"}
    return airdrop_current_json()


def build_and_airdrop_folder() -> dict:
    return airdrop_folder()
