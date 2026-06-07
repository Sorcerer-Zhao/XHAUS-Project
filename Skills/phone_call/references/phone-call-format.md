# phone-calls.json Format

**Path:** `memory/phone-calls.json` (workspace root)

```json
{
  "entries": [
    {
      "id": "2026-06-07-xinqiao",
      "title": "新桥烧肉订位",
      "to": "+8613853493619",
      "script": "你好，我想预订明天晚上六点，四位，姓张。谢谢。",
      "callAt": "2026-06-07T10:00:00+08:00",
      "mealAt": "2026-06-07T19:00:00+08:00",
      "location": "王府井银泰in88",
      "status": "scheduled",
      "createdAt": "2026-06-06T15:30:00+08:00",
      "reminders": {
        "t5": { "success": true },
        "t1": { "success": true },
        "t0": { "success": true }
      }
    }
  ]
}
```

## Fields

| Field | Required | Description |
|-------|:--------:|-------------|
| `id` | yes | `{YYYY-MM-DD}-{slug}` |
| `title` | yes | Short label for reminders |
| `to` | yes | E.164 phone number |
| `script` | yes | Confirmed spoken Chinese script |
| `callAt` | yes | Planned dial time (ISO-8601) |
| `mealAt` | no | Meal time for calendar event (ISO-8601) |
| `location` | no | Venue for calendar event |
| `status` | yes | `scheduled` / `completed` / `cancelled` / `completed_immediate` |
| `appleSync` | no | Contact + calendar sync results from `schedule_call.py` |
| `createdAt` | yes | When the entry was created |
| `reminders` | no | remindctl results per tier |

## Lifecycle

1. **scheduled** — created by `schedule_call.py`
2. **completed** — user finished the call (set manually or by user telling agent)
3. **cancelled** — user cancelled; delete matching Reminders
4. **completed_immediate** — immediate dial via `dial.py`

## Cleanup

Remove entries older than 14 days when adding new ones (except `scheduled` future entries).
