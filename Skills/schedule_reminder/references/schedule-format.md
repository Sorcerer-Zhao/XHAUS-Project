# Schedule JSON Format Reference

## File: `memory/schedule.json`

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
        "appleReminderIds": ["..."],
        "appleCalendarEventId": "..."
      }
    }
  ]
}
```

## Field Specifications

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier: `{date}-{event-slug}`. Lowercase, hyphens. |
| `event` | string | Event name, e.g. "猛古里自助午餐" |
| `date` | string | Date in `YYYY-MM-DD` format |
| `timeStart` | string | Start time in `HH:mm` format (24h) |
| `location` | string | Event location/address |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `timeEnd` | string | End time in `HH:mm` format (24h) |
| `origin` | string | Starting point / departure location |
| `transport` | string | "打车", "地铁", "驾车", "步行", etc. |
| `notes` | string | Any additional notes |
| `masterPreference` | object | User's attitude/importance for this event (see below) |
| `reminder-source` | object | Origin of this schedule entry (who proposed it, from which channel/group) |
| `createdAt` | string | ISO-8601 timestamp with timezone |
| `remindersSetup` | object | Tracks created cron/reminder/calendar IDs |

### masterPreference Object

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `importance` | string | `"high"` / `"medium"` / `"low"` | How important this event is to the user |
| `tone` | string | `"serious"` / `"casual"` / `"fun"` | Suggested tone for reminders and follow-ups |
| `description` | string | free text | Brief context about what this event means to the user |

**Usage of masterPreference:**

- `importance: "high"` → Use serious, urgent tone. Be punctual with reminders. Understand user's emotional investment.
- `importance: "medium"` → Standard reminders.
- `importance: "low"` → Light touch. One reminder is enough.
- `tone: "serious"` → Formal reminders, avoid jokes.
- `tone: "casual"` → Relaxed tone, can be playful.
- `tone: "fun"` → Enthusiastic, energetic reminders.

**When to infer masterPreference:**
- Interview / exam / medical appointment → `importance: "high"`, `tone: "serious"`
- Friend gathering / dinner / casual outing → `importance: "medium"`, `tone: "casual"`
- Party / celebration / fun activity → `importance: "medium"`, `tone: "fun"`
- If unsure, default to `importance: "medium"`, `tone: "casual"` and confirm with user

### remindersSetup Object

| Field | Type | Description |
|-------|------|-------------|
| `cronJobIds.dayBefore` | string | Cron job ID for T-1 day reminder |
| `cronJobIds.twoHoursBefore` | string | Cron job ID for T-2 hours reminder |
| `cronJobIds.oneHourBefore` | string | Cron job ID for T-1 hour reminder |
| `appleReminderId` | string | Apple Reminder ID created for this event |
| `appleCalendarEventId` | string | Apple Calendar event ID created for this event |

### reminder-source Object

| Field | Type | Description |
|-------|------|-------------|
| `proposer` | string | Who proposed/scheduled this event, e.g. "主人", "赵致睿" |
| `channel` | string | Originating platform: `"webchat"`, `"feishu"`, `"weixin"`, etc. |
| `groupId` | string, optional | Group chat ID if proposed in a group |
| `groupName` | string, optional | Group chat name if proposed in a group, e.g. "BJTU内部群" |

**Usage:** When delivering reminders, route back to the originating channel/group.
- If `source.channel == "webchat"` -> remind in webchat
- If `source.channel == "feishu"` and `source.groupId` exists -> remind in that Feishu group
- If `source.channel == "feishu"` and no groupId -> remind via direct message

## ID Generation

Format: `{YYYY-MM-DD}-{event-in-kebab-case}`

Examples:
- `2026-05-21-mengguli`
- `2026-05-25-meeting-with-zhang`
- `2026-06-01-fly-to-shanghai`

## Entry Lifecycle

1. **Created**: Entry added, reminders registered (3 cron jobs + Apple Reminder + Apple Calendar event)
2. **Reminding**: Three-tier reminder schedule:
   - T-1 day: "明天有安排，知会一声"
   - T-2 hours: "准备出发/准备了"
   - T-1 hour: "该出发了/最后提醒"
3. **Past**: Entry kept for 14 days, then auto-cleaned
4. **Deleted**: If user cancels, remove from JSON and delete all cron/reminder/calendar items

## Cleanup Rules

- **Auto-cleanup**: Remove entries older than 14 days from `schedule.json` when adding new entries (batch with the write operation)
- If a cron job or Apple Reminder fails to create, log the failure but do not delete the entry
- If user cancels an event: remove entry from JSON, delete all 3 cron jobs, complete/delete Apple Reminder, delete Apple Calendar event
- User can also manually request cleanup with a custom cutoff date
