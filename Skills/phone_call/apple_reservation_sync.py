"""预约确认后：写入 Mac 通讯录 + iCloud 日历（同步到 iPhone）。"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
DEFAULT_CALENDAR = "个人"
DEFAULT_MEAL_DURATION_HOURS = 2


def _escape_apple(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "osascript failed").strip()
        return False, err
    return True, (result.stdout or "").strip()


def _phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def save_contact(
    *,
    name: str,
    phone: str,
    notes: str = "",
    dry_run: bool = False,
) -> dict:
    """将餐厅/商户电话存入通讯录（组织名 + 电话号码）。"""
    name = name.strip() or "订位电话"
    phone = phone.strip()
    notes = notes.strip()
    digits = _phone_digits(phone)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "would_save": {"name": name, "phone": phone},
        }

    note_prop = f', note:"{_escape_apple(notes)}"' if notes else ""
    script = f'''
tell application "Contacts"
    set targetDigits to "{_escape_apple(digits)}"
    repeat with p in people
        repeat with ph in phones of p
            set phDigits to my normalizePhone(value of ph as text)
            if phDigits is targetDigits then
                return "existing:" & id of p as text
            end if
        end repeat
    end repeat
    set newPerson to make new person with properties {{organization:"{_escape_apple(name)}"{note_prop}}}
    make new phone at end of phones of newPerson with properties {{label:"work", value:"{_escape_apple(phone)}"}}
    return "created:" & id of newPerson as text
end tell

on normalizePhone(t)
    set out to ""
    repeat with i from 1 to length of t
        set c to character i of t
        if c is in "0123456789" then set out to out & c
    end repeat
    return out
end normalizePhone
'''.strip()

    ok, detail = _run_osascript(script)
    if not ok and "created:" not in detail and "existing:" not in detail:
        return {"success": False, "error": detail, "hint": "首次使用需在「系统设置 → 隐私 → 通讯录」允许终端/Cursor 访问通讯录"}
    status = "existing" if detail.startswith("existing:") else "created"
    person_id = detail.split(":", 1)[-1] if ":" in detail else detail
    return {"success": True, "status": status, "contact_id": person_id, "name": name, "phone": phone}


def save_meal_calendar_event(
    *,
    title: str,
    meal_at: datetime,
    location: str = "",
    duration_hours: float = DEFAULT_MEAL_DURATION_HOURS,
    calendar_name: str = DEFAULT_CALENDAR,
    dry_run: bool = False,
) -> dict:
    """将用餐时间写入 iCloud 日历（默认「个人」），同步到 iPhone。"""
    title = title.strip() or "用餐"
    location = location.strip()
    loc_prop = f', location:"{_escape_apple(location)}"' if location else ""

    if dry_run:
        end = meal_at + timedelta(hours=duration_hours)
        return {
            "success": True,
            "dry_run": True,
            "would_create": {
                "calendar": calendar_name,
                "title": title,
                "start": meal_at.isoformat(),
                "end": end.isoformat(),
                "location": location or None,
            },
        }

    script = f'''
tell application "Calendar"
    set targetCal to "{_escape_apple(calendar_name)}"
    set calExists to false
    repeat with cal in calendars
        if name of cal is targetCal then
            set calExists to true
            exit repeat
        end if
    end repeat
    if not calExists then
        error "Calendar not found: " & targetCal
    end if
    set startDate to current date
    set year of startDate to {meal_at.year}
    set month of startDate to {meal_at.month}
    set day of startDate to {meal_at.day}
    set time of startDate to ({meal_at.hour} * hours + {meal_at.minute} * minutes)
    set endDate to startDate + ({duration_hours} * hours)
    set newEvent to make new event at calendar targetCal with properties {{summary:"{_escape_apple(title)}"{loc_prop}, start date:startDate, end date:endDate}}
    return id of newEvent as text
end tell
'''.strip()

    ok, detail = _run_osascript(script)
    if not ok:
        return {
            "success": False,
            "error": detail,
            "hint": "需在「系统设置 → 隐私 → 日历」允许访问；日历须为 iCloud「个人」等可同步日历",
        }
    return {
        "success": True,
        "event_id": detail,
        "calendar": calendar_name,
        "title": title,
        "meal_at": meal_at.isoformat(),
        "location": location or None,
    }


def sync_reservation_to_apple(
    *,
    title: str,
    phone: str,
    script: str,
    meal_at: datetime | None,
    location: str = "",
    meal_duration_hours: float = DEFAULT_MEAL_DURATION_HOURS,
    calendar_name: str = DEFAULT_CALENDAR,
    skip_contact: bool = False,
    skip_calendar: bool = False,
    dry_run: bool = False,
) -> dict:
    out: dict = {"contact": None, "calendar": None}
    if not skip_contact:
        out["contact"] = save_contact(
            name=title,
            phone=phone,
            notes=script,
            dry_run=dry_run,
        )
    if not skip_calendar:
        if meal_at is None:
            out["calendar"] = {
                "success": False,
                "skipped": True,
                "error": "meal-at not provided",
            }
        else:
            out["calendar"] = save_meal_calendar_event(
                title=title,
                meal_at=meal_at,
                location=location,
                duration_hours=meal_duration_hours,
                calendar_name=calendar_name,
                dry_run=dry_run,
            )
    out["success"] = all(
        r is None or r.get("success") or r.get("skipped")
        for r in (out["contact"], out["calendar"])
    )
    return out
