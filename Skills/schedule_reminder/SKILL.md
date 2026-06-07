---
name: schedule-reminder
description: Detect scheduling intents from conversation - plans, appointments, future events with time/location. Extract structured data, persist to schedule table, set up proactive reminders via cron and Apple Reminders. Activate on Chinese scheduling phrases like 提醒我, 安排, 出发, or time references 周四/明天/下周.
---

# Schedule & Reminder Skill

## Trigger Detection

Activate when the user says anything that implies a future event:

- Time references: "周四", "明天", "下周一", "下个月", "2026-05-21", "几点"
- Verbs: "去", "要去", "想去", "打算", "安排", "提醒我", "记一下", "预约"
- Event types: "吃饭", "自助", "聚餐", "开会", "见面", "出发", "出发去"
- Context clues: interview, exam, medical appointment, travel, celebration

## Extraction: Parse Into Structured Fields

Extract these fields from the conversation:

| Field | Required | Example |
|-------|----------|---------|
| `event` | required | "猛古里吃自助午餐" |
| `date` | required | "2026-05-21" (周四) |
| `timeStart` | required | "11:00" |
| `timeEnd` | optional | "14:00" |
| `location` | required | "王府井银泰in88 3层" |
| `origin` | optional | "北京交通大学" |
| `transport` | optional | "打车/地铁" |
| `notes` | optional | "人均¥135" |
| `masterPreference` | optional | see below |
| `reminder-source` | optional | Who/channel/group the plan came from |

**Auto-capture reminder-source:**
- `proposer`: Use the sender name from conversation context
- `channel`: Use the current session's channel (`webchat`, `feishu`, `weixin`, etc.)
- `groupId` / `groupName`: If in a group chat, capture the group ID and name; if direct message, leave null

**Date inference rules:**

| User says | Interpret as |
|-----------|-------------|
| "周四" | Next Thursday from today |
| "明天" | Today + 1 day |
| "下周X" | Next week's day X |
| "这周五" | This week's Friday |
| "下个月" | Next month, same day if valid |

Use `session_status` to check today's date before computing relatives.

### masterPreference — 主人偏好

A field that captures what this event means to the user. Use it to calibrate tone and understand emotional context.

**Inference defaults:**

| Event type | importance | tone |
|-----------|------------|-------|
| Interview / exam / medical | `high` | `serious` |
| Friend gathering / dinner | `medium` | `casual` |
| Party / celebration | `medium` | `fun` |
| Business meeting | `high` | `serious` |
| Casual outing / shopping | `low` | `casual` |

**Structure:**
```json
"masterPreference": {
  "importance": "high",
  "tone": "casual",
  "description": "和好朋友聚餐，期待很久了"
}
```

When unsure, default to `medium/casual` and confirm with the user: "这个约对你来说重要吗？还是随便吃吃？"

**Tone adjustment rules:**
- `importance: "high"` -> Serious, urgent reminders. Multiple prompt layers. Empathetic if something goes wrong.
- `importance: "low"` -> Light touch. One reminder is fine.
- `tone: "serious"` -> Formal wording, no jokes.
- `tone: "casual"` -> Relaxed, could use "吃", "溜达", "玩" etc.
- `tone: "fun"` -> Enthusiastic, energetic, exclamation marks.

## Storage: Schedule Data Format

**File:** `memory/schedule.json`

Full format reference: [references/schedule-format.md](references/schedule-format.md)

```json
{
  "entries": [
    {
      "id": "2026-05-21-mengguli",
      "event": "猛古里吃自助午餐",
      "date": "2026-05-21",
      "timeStart": "11:00",
      "timeEnd": "14:00",
      "location": "王府井银泰in88 3层",
      "origin": "北京交通大学",
      "transport": "打车",
      "notes": "人均¥135，评分4.6",
      "masterPreference": {
        "importance": "medium",
        "tone": "casual",
        "description": "朋友聚餐，轻松场合"
      },
      "reminder-source": {
        "proposer": "主人",
        "channel": "webchat",
        "groupId": null,
        "groupName": null
      },
      "createdAt": "2026-05-19T23:55:00+08:00",
      "remindersSetup": {
        "cronJobIds": {
          "dayBefore": "...",
          "twoHoursBefore": "...",
          "oneHourBefore": "..."
        },
        "appleReminderId": "...",
        "appleCalendarEventId": "..."
      }
    }
  ]
}
```

**Read workflow:** Before any operation, read `memory/schedule.json`. If it doesn't exist, create it with `{"entries": []}`.

**Cleanup:** When reading or writing the file, remove any entries older than 14 days. Run cleanup as a batch step alongside the write.

## Registration: Set Up Three-Tier Reminders

After extracting and storing the schedule entry, create **3 cron jobs**, **1 Apple Reminder**, and **1 Apple Calendar event**.

### Reminder Schedule

| Tier | Timing | Purpose | Tone |
|------|--------|---------|------|
| **T-1 day** | Same time, day before | "明天有事，先记着" | Informational |
| **T-2 hours** | Event time - 2h | "差不多了，准备出发" | Action-oriented |
| **T-1 hour** | Event time - 1h | "该走了！" | Urgent |

### 1. Cron Jobs (In-Chat Proactive Reminders)

Create one cron job per tier. Use `delivery.mode` to route back to the source channel.

**Routing rules based on `reminder-source`:**
- If `source.channel == "webchat"` -> deliver to webchat (no special delivery config needed)
- If `source.channel == "feishu"` and `source.groupId` exists -> set `delivery.channel: "feishu"`, `delivery.to: source.groupId`
- If `source.channel == "feishu"` and no groupId -> deliver to feishu DM
- `delivery.mode: "announce"` to push notification out-of-band

**Group @mention rule:** When the reminder fires and `reminder-source` has a `groupId`, the reminder message **must @mention the proposer**. This ensures the person who scheduled the event gets pinged in the group.
  - Feishu: use `@proposer_name` or `at` user tag in message
  - Webchat: plain name mention is sufficient
  - Weixin: use @username format

**Common parameters:**
- `schedule.kind`: `"at"`
- `schedule.at`: ISO-8601 timestamp of trigger time
- `payload.kind`: `"systemEvent"`
- `deleteAfterRun`: `true`

**Naming:** `"remind-{id}-{tier}"` e.g. `"remind-2026-05-21-mengguli-daybefore"`

**Tier customization:**

**T-1 day text:**
> 明天{timeStart}你有安排：{event} @ {location}
> 记得准备好，别迟到哦

**T-2 hours text:**
> 两小时后：{event} @ {location}
> 从{origin}出发的话，该准备出门了

**T-1 hour text:**
> 1小时后：{event} @ {location}
> 出发建议：{transport}路线，预计{X}分钟到达
> 差不多该走了！

Adjust text tone based on `masterPreference`:
- `high/serious`: More formal, include backup plans
- `low/casual`: Shorter, more relaxed
- `fun`: Exclamation marks, playful

### 2. Apple Reminder (Native Push + Sound on iPhone/Mac)

```bash
remindctl add --title "⏰ {event}" \
  --notes "{location} · {notes}" \
  --due "{date} {timeStart}" \
  --list "日程提醒"
```

If the "日程提醒" list doesn't exist:
```bash
remindctl list "日程提醒" --create
```

**Note:** If `remindctl` returns "Reminders access: Not determined", tell the user to run `remindctl authorize` once to grant permission.

### 3. Apple Calendar Event (原生日历联动 → iCloud同步)

Create a calendar event via AppleScript in an **iCloud-synced calendar** so it automatically shows on iPhone/iPad.

> ⚠️ **关键：不能使用本地日历！** 本地日历（Source: Default/LOCAL）不会同步到其他设备。必须使用 iCloud CalDAV 日历。
> 中文用户的标准 iCloud 日历名称是 **"个人"**。如果有其他自定义 iCloud 日历名称，可在创建时调整。

**Step 1:** Verify "个人" iCloud calendar exists.

```bash
osascript -e '
tell application "Calendar"
   set targetCal to "个人"
   set calExists to false
   repeat with cal in calendars
      if name of cal is targetCal then
         set calExists to true
         exit repeat
      end if
   end repeat
   if not calExists then
      -- Create in iCloud: make new calendar at account named "iCloud" with properties {name:"个人"}
      make new calendar with properties {name:"个人"}
   end if
end tell
' 2>&1 > /dev/null
```

**Step 2:** Create the event in the iCloud "个人" calendar.

Do NOT use line continuations (`¬`) in the properties block — they cause AppleScript execution errors. Keep everything on one line.

```bash
YEAR="2026"; MONTH="5"; DAY="21"
HOUR="11"; MINUTE="0"
DURATION="3"  # hours
EVENT="猛古里自助午餐"
LOC="王府井银泰in88 3层"

EVENT_ID=$(osascript -e "
tell application \"Calendar\"
   set targetCal to \"个人\"
   set startDate to current date
   set year of startDate to $YEAR
   set month of startDate to $MONTH
   set day of startDate to $DAY
   set time of startDate to (${HOUR} * hours + ${MINUTE} * minutes)
   set endDate to startDate + (${DURATION} * hours)
   set newEvent to make new event at calendar targetCal with properties {summary:\"$EVENT\", location:\"$LOC\", start date:startDate, end date:endDate}
   return id of newEvent
end tell
")
```

**Important:**
- Use `summary`, `location`, `start date`, `end date` properties, all on one line inside the properties block
- The `description`/`notes` field sometimes causes type conversion errors; omit it if the script fails
- Capture `id of newEvent` and store in `remindersSetup.appleCalendarEventId`
- Verify the event was created in the correct calendar by checking Calendar.app → it should appear under "个人" (iCloud), not "日程" (On My Mac)

In practice, write the AppleScript with computed values substituted in. Example:

```bash
YEAR="2026"; MONTH="5"; DAY="21"
HOUR="11"; MINUTE="0"
DURATION="3"  # hours
EVENT="猛古里自助午餐"
LOC="王府井银泰in88 3层"

EVENT_ID=$(osascript -e "
tell application \"Calendar\"
   set targetCal to \"个人\"
   set startDate to current date
   set year of startDate to $YEAR
   set month of startDate to $MONTH
   set day of startDate to $DAY
   set time of startDate to (${HOUR} * hours + ${MINUTE} * minutes)
   set endDate to startDate + (${DURATION} * hours)
   set newEvent to make new event at calendar targetCal with properties {summary:\"$EVENT\", location:\"$LOC\", start date:startDate, end date:endDate}
   return id of newEvent
end tell
")
```

Capture the returned event ID and store it in `remindersSetup.appleCalendarEventId`.

## Cron Fire Handler: On Wake

When a cron systemEvent fires, it wakes the main session. On receiving the event:

1. Read `memory/schedule.json`
2. Identify which entry and which tier triggered
3. Format the notification with the right tone based on `masterPreference`
4. Send to user in the active conversation

### Tone Adjustment Example

- `importance: "high"`, `tone: "serious"`
  -> "主人，提醒您明天11:00在王府井银泰in88有您记录的聚餐安排。请提前准备。"
- `importance: "medium"`, `tone: "casual"`
  -> "明天11点猛古里吃自助，别忘了！"
- `importance: "low"`, `tone: "casual"`
  -> "明天好像有个饭局？猛古里，11点，记一下就行。"

## Maintenance

### Upcoming Events Check

When the user asks "我今天有什么安排" / "今天有什么日程":

1. Read `memory/schedule.json`
2. Filter entries matching today or tomorrow
3. Present sorted by time, with masterPreference context if useful

### Cleanup

- **Auto-cleanup**: When writing new entries, also remove entries older than 14 days from `schedule.json`
- If a cron job or Apple Reminder/Calendar event fails to create, log the failure but keep the entry
- If user cancels an event: remove entry, delete all 3 cron jobs, complete/delete Apple Reminder, delete Apple Calendar event
- User can also manually request cleanup with a custom cutoff date

## Example Workflow

User: "周四中午去猛古里吃自助，从北交出发"

1. Parse fields:
   - `event`: "猛古里自助午餐"
   - `date`: compute Thursday = "2026-05-21" (via `session_status`)
   - `timeStart`: "11:00" (default lunch time since user said "中午")
   - `timeEnd`: "14:00" (buffet default)
   - `location`: "王府井银泰in88 3层"
   - `origin`: "北京交通大学"
   - `masterPreference`: default to `medium/casual` (dinner with friend)
2. Confirm with user: "这个约重要吗？还是随便吃吃？" (if not obvious)
3. Write entry to `memory/schedule.json`, cleaning up entries older than 14 days at the same time
4. Create 3 cron jobs:
   - `2026-05-20T11:00:00+08:00` (T-1 day)
   - `2026-05-21T09:00:00+08:00` (T-2 hours)
   - `2026-05-21T10:00:00+08:00` (T-1 hour)
5. Create Apple Reminder: `remindctl add --title "猛古里自助午餐" --due "2026-05-21 11:00" --list "日程提醒"`
6. Create Apple Calendar event via osascript
7. Confirm: "记好了！周四会提前1天、2小时、1小时三次提醒你，Apple日历和提醒事项也已同步 🎯"
