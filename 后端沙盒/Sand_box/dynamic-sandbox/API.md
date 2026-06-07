# 动态模拟沙盒后端 · API 契约 (API.md)

> Base URL: `http://127.0.0.1:8787`
> 配套架构见 `SANDBOX_SPEC.md`。本文件给出**逐端点**的 method + path + query/body + 响应示例 JSON。
> 所有响应均为 `application/json; charset=utf-8`，中文不转义 (`ensure_ascii=False`)。
> 时间字段：`sim_time`/`*_at` 为**世界时间**(`world.sim_now`)；`real_time` 为真实墙钟，仅供对时。

---

## 端点总览

| # | Method | Path | 用途 | 对应 skill |
|---|---|---|---|---|
| 1 | GET | `/` | 健康检查 + 世界概览 | — |
| 2 | GET | `/health` | 存活探针 | — |
| 3 | GET | `/restaurants` | 餐厅列表/筛选 | food-guide |
| 4 | GET | `/restaurants/{id}` | 单餐厅详情 | food-guide |
| 5 | POST | `/queue/take` | 取号 | food-guide(queue) |
| 6 | GET | `/queue/status` | 查排队进度 | food-guide(queue) |
| 7 | POST | `/queue/cancel` | 取消排队 | food-guide(queue) |
| 8 | GET | `/weather` | 天气(仿 open-meteo) | weather |
| 9 | GET | `/mobility/areas` | 区域 + 出行配置 | mobility-planner |
| 10 | GET | `/mobility/plan` | 出行方案对比 | mobility-planner |
| 11 | GET | `/entertainment` | 娱乐场所列表/筛选 | entertainment-scout |
| 12 | GET | `/entertainment/{id}` | 单娱乐详情 | entertainment-scout |
| 13 | GET | `/events` | 世界事件流(增量) | 任务③ 管家心跳 |
| 14 | POST | `/admin/inject` | 控场:注入剧情 | E7 demo |
| 15 | POST | `/admin/clock` | 控场:改倍速/暂停 | E7 demo |
| 16 | POST | `/admin/reset` | 控场:重置世界 | E7 demo |
| 17 | GET | `/admin/state` | 控场:看世界全局快照 | E7 debug |

---

## 1. GET `/` — 健康检查 + 世界概览

**响应:**
```json
{
  "service": "全天候私人管家 · 动态沙盒",
  "version": "1.0",
  "sim_now": "2026-06-07T19:12:35",
  "time_scale": 30.0,
  "tick_seconds": 5.0,
  "tick_count": 142,
  "paused": false,
  "counts": { "restaurants": 14, "venues": 15, "areas": 15, "active_queue": 3 },
  "weather": { "weather_code": 61, "is_raining": true, "temperature": 22.4 },
  "latest_event_seq": 87
}
```

## 2. GET `/health`
```json
{ "status": "ok", "tick_count": 142, "sim_now": "2026-06-07T19:12:35" }
```

---

## 3. GET `/restaurants` — 餐厅列表 / 筛选

**Query (全部可选):**

| 参数 | 类型 | 说明 |
|---|---|---|
| `area` | str | 区域模糊匹配 (匹配 area 或 address) |
| `cuisine` | str | 菜系模糊匹配 (匹配 cuisine 或 tags) |
| `tag` | str | 标签模糊匹配 |
| `budget` | int | 人均×people ≤ budget;无结果软兜底略超 20% |
| `people` | int | 人数,默认 1 |
| `sort` | str | `rating`(默认)\|`price`\|`wait` |
| `limit` | int | Top-N,默认 5 |

**响应 (结构对齐现有 search-restaurants.js 输出 + 单店字段对齐 mock-restaurants.json):**
```json
{
  "query": { "area": "望京", "sort": "wait" },
  "count": 2,
  "total": 5,
  "hint": "共 5 家符合，已为你优选前 5 家",
  "sim_now": "2026-06-07T19:12:35",
  "restaurants": [
    {
      "id": "r003",
      "name": "村上一屋",
      "cuisine": "日料",
      "area": "望京",
      "address": "望京西园四区416号楼底商",
      "rating": 4.5,
      "pricePerPerson": 82,
      "tags": ["拉面", "定食", "性价比"],
      "openHours": "10:30-22:00",
      "phone": "010-6478-XXXX",
      "waitInfo": { "currentWait": 0, "avgWaitMinutes": 0 },
      "highlights": ["豚骨拉面量大实惠", "午市定食套餐 58 元", "不用等位"],
      "seatsFree": 6,
      "isFull": false
    },
    {
      "id": "r004",
      "name": "海底捞火锅(望京店)",
      "cuisine": "火锅",
      "area": "望京",
      "address": "望京街10号望京SOHO T2-5F",
      "rating": 4.6,
      "pricePerPerson": 135,
      "tags": ["火锅", "服务好", "夜宵"],
      "openHours": "10:00-次日07:00",
      "phone": "010-6470-XXXX",
      "waitInfo": { "currentWait": 14, "avgWaitMinutes": 63 },
      "highlights": ["服务体验天花板", "番茄锅底绝了", "生日有惊喜"],
      "seatsFree": 0,
      "isFull": true
    }
  ]
}
```
> 兼容说明：`waitInfo` 由后台演化的 `queue_waiting / turnover_min_per_table` 实时派生。`seatsFree/isFull` 为本沙盒新增的动态字段,现有 skill 忽略即可,不影响其读取。

## 4. GET `/restaurants/{id}`
```json
{
  "id": "r004", "name": "海底捞火锅(望京店)", "cuisine": "火锅", "area": "望京",
  "address": "望京街10号望京SOHO T2-5F", "rating": 4.6, "pricePerPerson": 135,
  "tags": ["火锅","服务好","夜宵"], "openHours": "10:00-次日07:00", "phone": "010-6470-XXXX",
  "waitInfo": { "currentWait": 14, "avgWaitMinutes": 63 },
  "highlights": ["服务体验天花板","番茄锅底绝了","生日有惊喜"],
  "seatsFree": 0, "isFull": true, "capacity": 60, "sim_now": "2026-06-07T19:12:35"
}
```
404: `{ "detail": "找不到餐厅 r999" }`

---

## 5. POST `/queue/take` — 取号

**Body:**
```json
{ "restaurant_id": "r004", "people": 2, "customer_name": "宋先生" }
```

**响应 (字段对齐现有 queue-number.js take 输出: queue_code/restaurant/ahead/eta_min/table_type):**
```json
{
  "success": true,
  "queue_code": "海07",
  "restaurant_id": "r004",
  "restaurant": "海底捞火锅(望京店)",
  "address": "望京街10号望京SOHO T2-5F",
  "table_type": "small",
  "table_type_label": "小桌（1-2人）",
  "people": 2,
  "customer_name": "宋先生",
  "ahead": 8,
  "eta_min": 36,
  "status": "waiting",
  "taken_at": "2026-06-07T19:12:35",
  "estimated_call_time": "19:48",
  "tips": ["⏰ 等待较长，可以先去附近逛逛，快到号时我会提醒你", "🌟 推荐必点：服务体验天花板、番茄锅底绝了"]
}
```
失败: `{ "success": false, "error": "找不到餐厅 r999" }`

## 6. GET `/queue/status` — 查进度

**Query:** `queue_code` (必填) — 例 `/queue/status?queue_code=海07`

**响应 (字段对齐: queue_code/status/ahead/eta_min/status_text):**
```json
{
  "success": true,
  "queue_code": "海07",
  "restaurant": "海底捞火锅(望京店)",
  "address": "望京街10号望京SOHO T2-5F",
  "table_type": "小桌（1-2人）",
  "people": 2,
  "status": "waiting",
  "ahead": 3,
  "eta_min": 14,
  "status_text": "排队中，前面还有 3 桌",
  "estimated_call_time": "19:26",
  "progress": "已服务 5 桌",
  "sim_now": "2026-06-07T19:21:05"
}
```
叫号后:
```json
{
  "success": true, "queue_code": "海07", "restaurant": "海底捞火锅(望京店)",
  "status": "called", "ahead": 0, "eta_min": 0,
  "status_text": "🔔 已叫号！请尽快前往餐厅就座", "sim_now": "2026-06-07T19:34:00"
}
```
其他状态 `status_text`: `seated→"已入座"`,`cancelled→"已取消"`。
404: `{ "success": false, "error": "找不到排队号 海99" }`

## 7. POST `/queue/cancel`
**Body:** `{ "queue_code": "海07" }`
```json
{ "success": true, "queue_code": "海07", "status": "cancelled", "message": "排队号 海07 已取消" }
```
非 waiting 不可取消: `{ "success": false, "error": "排队号 海07 当前状态「已叫号」，无法取消" }`

---

## 8. GET `/weather` — 天气 (仿 open-meteo)

**Query (可选):** `area` (默认全城统一一份天气;传 area 也返回同一份,字段含 resolved area) 或 `lat`/`lon`(占位,返回同一份)。

**响应 (严格仿 open-meteo Forecast API,字段名与 current/daily 对齐 weather skill 读法):**
```json
{
  "latitude": 39.997,
  "longitude": 116.474,
  "timezone": "Asia/Shanghai",
  "area": "望京",
  "sim_now": "2026-06-07T19:21:05",
  "current": {
    "time": "2026-06-07T19:21",
    "temperature_2m": 22.4,
    "apparent_temperature": 21.1,
    "relative_humidity_2m": 86,
    "wind_speed_10m": 18.5,
    "weather_code": 61
  },
  "daily": {
    "time": ["2026-06-07", "2026-06-08", "2026-06-09"],
    "temperature_2m_max": [27.0, 29.5, 31.0],
    "temperature_2m_min": [19.0, 20.0, 21.5],
    "weather_code": [61, 80, 0]
  },
  "is_raining": true
}
```
> 兼容说明: weather skill 读 `current.temperature_2m / apparent_temperature / relative_humidity_2m / wind_speed_10m / weather_code` 和 `daily.temperature_2m_max/min + weather_code`,本响应字段名逐一对齐,可直接替换 open-meteo URL。`is_raining` 为冗余便利字段。

---

## 9. GET `/mobility/areas` — 区域坐标 + 出行配置

**响应 (结构原样对齐 mock-areas.json,含全部 15 区域):**
```json
{
  "areas": {
    "望京": { "lat": 39.997, "lon": 116.474, "stations": [ { "name": "望京站", "lines": ["14号线","15号线"] }, { "name": "望京西站", "lines": ["13号线","15号线"] } ] },
    "三里屯": { "lat": 39.934, "lon": 116.454, "stations": [ { "name": "团结湖站", "lines": ["10号线"] }, { "name": "东大桥站", "lines": ["6号线"] } ] }
  },
  "subwayConfig": { "avgSpeedKmH": 35, "transferMinutes": 5, "walkToStationMinutes": 6,
    "priceRules": { "base": 3, "thresholds": [ {"km":6,"price":3},{"km":12,"price":4},{"km":22,"price":5},{"km":32,"price":6} ] } },
  "taxiConfig": { "baseFare": 13, "baseKm": 3, "perKm": 2.3, "peakMultiplier": 1.3, "nightMultiplier": 1.2,
    "peakHours": ["07:00-09:30","17:00-20:00"], "nightHours": ["23:00-05:00"],
    "avgSpeedKmH": { "normal": 28, "peak": 18 },
    "rainSurge": 1.5, "currentSurge": 1.5 },
  "walkConfig": { "speedKmH": 5, "maxRecommendKm": 3 }
}
```
> 兼容说明: `areas/subwayConfig/taxiConfig/walkConfig` 与现有完全一致,mobility-planner 的本地算法可继续跑。`taxiConfig.currentSurge` 是新增的**动态**字段(雨天=1.5,晴天=1.0),skill 可选用以反映实时加价;不用也不影响。

## 10. GET `/mobility/plan` — 出行方案对比 (沙盒侧已算好,含联动)

**Query:** `from`(必), `to`(必), `time`(可选 `HH:MM`,默认用 sim_now), `mode`(可选 `all|subway|taxi|walk|bike`)

**响应 (结构对齐 plan-route.js 输出: plans[] 每项 mode/duration/cost/...):**
```json
{
  "success": true,
  "from": "望京",
  "to": "三里屯",
  "distance": "9.8 km",
  "departureTime": "19:21",
  "recommended": "🚇 地铁",
  "weatherNote": "雨天打车加价并易堵,地铁更稳",
  "plans": [
    { "mode": "🚇 地铁", "duration": "约 32 分钟", "durationMinutes": 32, "cost": "¥4", "costValue": 4,
      "route": "望京站（14号线）→ 换乘 → 团结湖站（10号线）", "transfers": 1, "arrivalTime": "19:53",
      "pros": ["准时可控，不受堵车影响","费用最低"], "cons": ["需要换乘","步行到站约 6 分钟"] },
    { "mode": "🚕 打车", "duration": "约 33-43 分钟", "durationMinutes": 38, "cost": "¥48-72", "costValue": 60,
      "distance": "9.8 km", "arrivalTime": "19:59", "peakWarning": true, "surge": 1.5,
      "weatherNote": "雨天打车需求大、加价约 1.5x", "pros": ["门到门，最省力"], "cons": ["⚠️ 雨天易堵","当前加价 1.5x"] }
  ]
}
```
> 联动 (E6): 当 `world.weather.is_raining` 时,taxi 的 `surge=1.5`、`costValue`/`durationMinutes` 已上浮,walk 给「雨天不建议」cons,响应级 `weatherNote` 提示。晴天 surge=1.0、无 weatherNote。
错误: `{ "success": false, "error": "无法识别出发地「火星」", "hint": "支持的区域：798、望京、三里屯、..." }`

---

## 11. GET `/entertainment` — 娱乐场所列表 / 筛选

**Query (全部可选):** `area`, `type`(movie|bar|ktv|escape_room|board_game|park|fitness|spa|massage|billiards|shopping|all), `time`(`HH:MM`), `people`, `budget`, `mood`(quiet|lively|active|relaxed), `limit`

**响应 (venues[] 各对象字段对齐 mock-entertainment.json):**
```json
{
  "query": { "area": "三里屯", "type": "all", "time": "21:00" },
  "count": 3,
  "sim_now": "2026-06-07T21:00:00",
  "weatherNote": "正在下雨，已为你降低了户外场所的优先级",
  "venues": [
    {
      "id": "e002", "name": "Blue Note Beijing", "type": "bar", "typeLabel": "🎵 爵士酒吧",
      "area": "三里屯", "address": "三里屯南路27号", "rating": 4.7, "priceRange": "150-300",
      "openHours": "19:00-次日02:00", "tags": ["爵士","现场演出","鸡尾酒","约会"],
      "highlights": ["每晚现场爵士乐演出","招牌Old Fashioned","氛围感拉满"],
      "tonightEvent": { "name": "Jazz Night — Trio Session", "time": "20:30", "coverCharge": 100 },
      "isOpenNow": true
    },
    {
      "id": "e006", "name": "X密室逃脱(三里屯旗舰店)", "type": "escape_room", "typeLabel": "🔐 密室逃脱",
      "area": "三里屯", "address": "工体北路甲2号盈科中心B1", "rating": 4.8, "priceRange": "128-198/人",
      "openHours": "10:00-23:00", "tags": ["密室","沉浸式","恐怖","推理"],
      "themes": [
        { "name": "末日危途", "themeName": "末日危途", "difficulty": "⭐⭐⭐⭐", "duration": "70分钟", "players": "4-6人", "price": 168, "genre": "科幻冒险", "availableSlots": ["20:30"] },
        { "name": "午夜博物馆", "themeName": "午夜博物馆", "difficulty": "⭐⭐⭐", "duration": "60分钟", "players": "2-4人", "price": 138, "genre": "悬疑推理", "availableSlots": ["21:00"] }
      ],
      "isOpenNow": true
    },
    {
      "id": "e007", "name": "望京公园", "type": "park", "typeLabel": "🌿 公园",
      "area": "望京", "address": "望京阜安西路", "rating": 4.2, "priceRange": "免费",
      "openHours": "06:00-22:00", "tags": ["散步","免费","夜景","遛弯"],
      "highlights": ["湖边步道适合饭后散步","夜间有灯光","安静舒适"],
      "isOpenNow": false, "isOutdoor": true, "weatherDemoted": true, "weatherNote": "雨天不建议户外"
    }
  ]
}
```
> 兼容说明:
> - 主题对象同时给 `name`(现有 mock 字段,skill 当前读法)与 `themeName`(prompt schema 别名),值相同,两种读法都成立。
> - 电影 `shows[]` 含 `availableSlots`/`spotsLeft` 不适用,沿用 `{movie,time,endTime,price,hall,rating}`;`ktv.packages`/`fitness.classes` 字段不变(`classes[].spotsLeft` 会随后台演化变化)。
> - `isOpenNow/isOutdoor/weatherDemoted/weatherNote` 为新增动态字段,联动雨天关闭/降权户外场所(E6),旧 skill 忽略即可。

## 12. GET `/entertainment/{id}`
返回单个 venue 对象 (同上单元素结构) + `sim_now`。404: `{ "detail": "找不到场所 e999" }`

---

## 13. GET `/events` — 世界事件流 (任务③ 主动协同)

**Query:**

| 参数 | 类型 | 说明 |
|---|---|---|
| `since` | int | 只返回 `seq > since` 的事件,默认 0;**幂等去重主键** |
| `limit` | int | 最多返回条数,默认 100 |
| `type` | str | 可选,按事件 type 过滤 (逗号分隔多类型) |

**响应:**
```json
{
  "since": 80,
  "latest_seq": 87,
  "count": 4,
  "sim_now": "2026-06-07T19:25:10",
  "events": [
    { "seq": 84, "id": "evt-000084", "type": "weather.changed", "severity": "notice",
      "sim_time": "2026-06-07T19:22:00", "real_time": "2026-06-07T11:02:13",
      "subject": { "kind": "weather", "area": "全城" },
      "payload": { "weather_code": 61, "is_raining": true, "temperature": 22.4 },
      "message": "🌧️ 望京一带开始下雨了" },
    { "seq": 85, "id": "evt-000085", "type": "venue.closed", "severity": "notice",
      "sim_time": "2026-06-07T19:22:00", "real_time": "2026-06-07T11:02:13",
      "subject": { "kind": "venue", "id": "e007", "name": "望京公园", "area": "望京" },
      "payload": { "reason": "rain" },
      "message": "🌿 望京公园因降雨暂不推荐,已为你降权" },
    { "seq": 86, "id": "evt-000086", "type": "mobility.surge", "severity": "notice",
      "sim_time": "2026-06-07T19:22:00", "real_time": "2026-06-07T11:02:13",
      "subject": { "kind": "mobility", "area": "全城" },
      "payload": { "surge": 1.5, "reason": "rain" },
      "message": "🚕 雨天打车需求上升,当前加价约 1.5x" },
    { "seq": 87, "id": "evt-000087", "type": "restaurant.full", "severity": "alert",
      "sim_time": "2026-06-07T19:24:30", "real_time": "2026-06-07T11:02:25",
      "subject": { "kind": "restaurant", "id": "r004", "name": "海底捞火锅(望京店)", "area": "望京" },
      "payload": { "seats_free": 0, "queue_waiting": 16 },
      "message": "🍲 海底捞火锅(望京店)已满座,当前排队 16 桌" }
  ]
}
```

**管家心跳消费范式 (任务③):**
```
state.lastSeq = 0
每 N 秒:
  resp = GET /events?since=state.lastSeq
  for e in resp.events:        # 已保证 seq > lastSeq, 无重复
      handle(e)                # 据 type 主动发起动作:
                               #   queue.threshold → 提醒用户/预约叫车
                               #   queue.called    → 通知就座
                               #   restaurant.full → 改荐替代餐厅
                               #   weather.changed → 重排室内娱乐+改出行
  state.lastSeq = resp.latest_seq
```
> 幂等: 即使心跳重叠/重试,只要带正确 `since` 就不会重复处理;`seq` 严格单调,`id` 为其字符串别名供日志关联。

---

## 14. POST `/admin/inject` — 控场: 注入剧情 (E7)

**Body (kind 决定剧情):**

| kind | 额外字段 | 效果 | 触发事件 |
|---|---|---|---|
| `rain` | — | 立刻下雨(code=61)并锁定,触发全套联动 | weather.changed + venue.closed + mobility.surge |
| `clear` | — | 立刻转晴(code=0)并解锁,复位联动 | weather.changed |
| `restaurant_full` | `restaurant_id` | 该店 seats_free=0、is_full=true | restaurant.full |
| `restaurant_seats` | `restaurant_id`, `seats`(默认5) | 该店立刻剩 N 桌 | restaurant.has_seat |
| `queue_surge` | `restaurant_id`, `waiting`(默认15) | 该店排队立刻涨到 N 桌 | restaurant.queue_surge |
| `queue_threshold` | `queue_code` | 该票 ahead 立刻=5 | queue.threshold |
| `queue_called` | `queue_code` | 该票立刻 called | queue.called |
| `venue_closed` | `venue_id` | 该场所立刻关闭 | venue.closed |

**示例 Body:** `{ "kind": "restaurant_full", "restaurant_id": "r002" }`

**响应:**
```json
{
  "success": true,
  "kind": "restaurant_full",
  "applied": { "restaurant_id": "r002", "seats_free": 0, "is_full": true },
  "event": { "seq": 91, "id": "evt-000091", "type": "restaurant.full",
             "message": "🍣 [控场] 松子日本料理 已被设为满座" },
  "sim_now": "2026-06-07T19:26:00"
}
```
失败: `{ "success": false, "error": "未知 kind: xxx,允许: rain|clear|restaurant_full|..." }`

## 15. POST `/admin/clock` — 控场: 改世界倍速 / 暂停 (E7)

**Body (字段均可选,只改传入的):**
```json
{ "time_scale": 30, "tick_seconds": 5.0, "paused": false }
```
**响应:**
```json
{
  "success": true,
  "time_scale": 30.0, "tick_seconds": 5.0, "paused": false,
  "note": "世界已提速 30x: 真实 5s = 世界 2.5min,10min 演化约 20s 看完",
  "sim_now": "2026-06-07T19:26:05"
}
```

## 16. POST `/admin/reset` — 控场: 重置世界 (E7)

**Body (可选):** `{ "seed": 42 }` — 传 seed 则可复现同一随机世界。
```json
{ "success": true, "message": "世界已重置", "seed": 42, "sim_now": "2026-06-07T18:00:00",
  "counts": { "restaurants": 14, "venues": 15, "areas": 15 } }
```

## 17. GET `/admin/state` — 控场: 世界全局快照 (debug)
```json
{
  "sim_now": "2026-06-07T19:26:05", "time_scale": 30.0, "tick_count": 312, "paused": false,
  "weather": { "weather_code": 61, "is_raining": true, "temperature": 22.4, "trend": "cooling" },
  "restaurants": [ { "id": "r004", "name": "海底捞火锅(望京店)", "seats_free": 0, "queue_waiting": 16, "is_full": true } ],
  "venues_closed": ["e007", "e015"],
  "active_queue": [ { "queue_code": "海07", "status": "waiting", "ahead": 3, "eta_min": 14 } ],
  "event_seq": 91,
  "scripted_overrides": { "weather_locked": true }
}
```

---

## 错误约定

- 业务失败 (找不到资源等): HTTP 200 + `{"success": false, "error": "..."}`(对齐现有 skill 习惯,便于无脑解析)。
- 路径级 404 (`/restaurants/{id}` 等用 FastAPI `HTTPException`): HTTP 404 + `{"detail": "..."}`。
- 入参校验失败 (pydantic): HTTP 422 + FastAPI 标准校验体。

## CORS
全开 (`allow_origins=["*"]`),便于浏览器端 demo 直接 fetch。
