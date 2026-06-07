# 全天候私人管家 · 动态模拟沙盒后端

> 美团黑客松 · **赛题任务④「自建动态 Mock 后端」** + 任务③「7×24 主动协同」基座
>
> 单进程 FastAPI 沙盒：进程内存里跑着一个**活的世界** `WorldState`，由后台 asyncio 时钟
> 主动演化（餐厅会自己坐满、排队会自己推进、天会自己下雨、雨天会连锁影响娱乐/出行）。
> HTTP 路由层只负责"观测/写入"这个世界，绝不自己临时算随机数。
>
> 核心卖点一句话：**数据是「活」的——不是用户来查时才临时编一个随机数，而是后台有一个真实在跑的世界，用户只是在某个时刻去观测它。**

详细架构契约见 [`SANDBOX_SPEC.md`](./SANDBOX_SPEC.md)，逐端点出入参见 [`API.md`](./API.md)。

---

## 0. 项目定位（赛题映射）

| 赛题点 | 落地 |
|---|---|
| **E1** 自建 FastAPI Mock 后端 | `app/main.py` + 7 个 router（餐厅/排队/天气/出行/娱乐/事件流/控场）|
| **E2** 后台时钟主动演化（非查询时才算）| `app/world/clock.py` 的 `world_clock_loop()`，由 lifespan 在 startup 拉起，每 ~5s 真实时间一个 tick 主动改世界 |
| **E3** 非静态、可复现「10 分钟内有位→已满」| 餐厅 `seats_free` 随机游走 + 概率涨满；配合时钟倍速 30 秒看完 |
| **E4** 演化带随机性 | 随机游走 / 概率翻台 / 概率涨满 / 天气马尔可夫转移，全部基于可 seed 的 `world.rng` |
| **E5** 接口覆盖 skill 全部数据 | restaurants / queue / weather / mobility / entertainment 五大类 |
| **E6 [加分]** 多类数据联动 | 下雨 → 餐厅排队变长 + 室外娱乐关闭/降权 + 打车加价 + ETA 变长（一处实现，多处生效）|
| **E7 [加分]** 演示控场 | `/admin/inject` 注入剧情、`/admin/clock` 改倍速、`/admin/reset` 重置、`/admin/state` 看全局 |
| **任务③** 7×24 主动协同 | `GET /events?since=` 增量事件流，每条带单调递增 `seq` 做幂等去重 |

---

## 1. 运行环境（已核实）

| 项 | 值 |
|---|---|
| Python | 3.13.5 (anaconda)，命令一律 `python3` |
| Web 框架 | FastAPI 0.115.9（全局已装）|
| ASGI 服务器 | uvicorn 0.34.2（全局已装）|
| pydantic | 2.10.3（v2 语法）|
| venv | **不需要**，直接全局跑 |
| 端口 | **8787**（已确认空闲）|
| 目录 | `Jensen_Song/dynamic-sandbox/`（相对仓库根）|

依赖已全局安装，`requirements.txt` 仅留痕。如需在新环境复现：

```bash
cd dynamic-sandbox
python3 -m pip install -r requirements.txt
```

---

## 2. 如何启动

### 方式 A：用 run.sh（推荐）

首次需要给脚本加可执行权限（只需一次）：

```bash
cd dynamic-sandbox
chmod +x run.sh
./run.sh
```

### 方式 B：直接敲 uvicorn（无需 chmod）

```bash
cd dynamic-sandbox
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --no-access-log
```

### ⚠️ 为什么不用 `--reload`（重要）

本沙盒是**有状态单进程**：后台 asyncio 时钟在进程内存里驱动整个世界。
`--reload` 会以子进程方式热重载、频繁杀死/重建进程，导致**后台时钟被杀、内存世界丢失、演化中断**。
所以 `run.sh` 用的是**单 worker + `--no-access-log`**，刻意不带 `--reload`（详见 `SANDBOX_SPEC.md` §0/§2）。
开发期若确需改代码自动重载，可临时手动加 `--reload`，但要接受"每次改动世界都被重置"。

### 启动后自检

```bash
curl -s http://127.0.0.1:8787/health
curl -s http://127.0.0.1:8787/            # 世界概览：sim_now / time_scale / tick_count / weather
```

看到 `tick_count` 随时间增长，就说明后台世界时钟在跑（E2 已生效）。

---

## 3. 端点速览表

Base URL：`http://127.0.0.1:8787`

| # | Method | Path | 用途 | 对应 skill |
|---|---|---|---|---|
| 1 | GET | `/` | 健康检查 + 世界概览 | — |
| 2 | GET | `/health` | 存活探针 | — |
| 3 | GET | `/restaurants` | 餐厅列表/筛选（`area/cuisine/tag/budget/people/sort/limit`）| food-guide |
| 4 | GET | `/restaurants/{id}` | 单餐厅详情 | food-guide |
| 5 | POST | `/queue/take` | 取号（body: `restaurant_id/people/customer_name`）| food-guide(queue) |
| 6 | GET | `/queue/status` | 查排队进度（query: `queue_code`）| food-guide(queue) |
| 7 | POST | `/queue/cancel` | 取消排队（body: `queue_code`）| food-guide(queue) |
| 8 | GET | `/weather` | 天气，仿 open-meteo（query: `area` 或 `lat/lon`）| weather |
| 9 | GET | `/mobility/areas` | 15 区域坐标 + 出行配置 | mobility-planner |
| 10 | GET | `/mobility/plan` | 出行方案对比（query: `from/to/time/mode`）| mobility-planner |
| 11 | GET | `/entertainment` | 娱乐场所列表/筛选（`area/type/time/people/budget/mood/limit`）| entertainment-scout |
| 12 | GET | `/entertainment/{id}` | 单娱乐详情 | entertainment-scout |
| 13 | GET | `/events` | 世界事件流增量（query: `since/limit/type`）| 任务③ 管家心跳 |
| 14 | POST | `/admin/inject` | 控场：注入剧情 | E7 demo |
| 15 | POST | `/admin/clock` | 控场：改倍速/暂停 | E7 demo |
| 16 | POST | `/admin/reset` | 控场：重置世界 | E7 demo |
| 17 | GET | `/admin/state` | 控场：世界全局快照 | E7 debug |

> 交互式文档：启动后浏览器开 `http://127.0.0.1:8787/docs`（FastAPI 自带 Swagger UI）。

---

## 4. 演示控场 Cookbook（E7 现场控场手册）

目标：在评委面前**确定性地**触发剧情，不靠"运气等它自己发生"。所有控场走 `/admin/*`。
一键跑完整故事可直接用 [`demo_client.py`](#6-demo_clientpy一键讲故事)；下面是手动逐条触发的"招式卡"。

### 4.1 先把世界加速：30 秒看完 10 分钟演化

```bash
curl -s -X POST http://127.0.0.1:8787/admin/clock \
  -H 'Content-Type: application/json' \
  -d '{"time_scale": 30}'
```

- `time_scale=30` 表示**世界时间走真实时间的 30 倍**。真实 5 秒一个 tick → 世界前进 150 秒（2.5 分钟）。
- 想看 10 分钟世界演化，真实只需约 `10*60/30 ≈ 20` 秒。
- 现场如果想"更快出效果"，可调到 `60`；想边讲边看，用 `20`。
- 暂停/恢复：`{"paused": true}` / `{"paused": false}`（讲解时定格世界很有用）。

### 4.2 一定触发「餐厅满座」

不等它自然坐满，直接钉死：

```bash
# 让 r004（海底捞望京店）立刻满座，会 push 一条 restaurant.full 事件
curl -s -X POST http://127.0.0.1:8787/admin/inject \
  -H 'Content-Type: application/json' \
  -d '{"kind": "restaurant_full", "restaurant_id": "r004"}'
```

随后 `GET /restaurants/r004` 会看到 `isFull: true / seatsFree: 0`，`GET /events?since=0` 里多一条 `restaurant.full`。

### 4.3 一定触发「排队剩 5 桌 / 叫号」

```bash
# 1) 先取个号，拿到 queue_code（例如返回 海07）
curl -s -X POST http://127.0.0.1:8787/queue/take \
  -H 'Content-Type: application/json' \
  -d '{"restaurant_id": "r004", "people": 2, "customer_name": "宋先生"}'

# 2) 把这张票的 ahead 直接钉到 5 → 触发 queue.threshold（"前面只剩5桌"提醒）
curl -s -X POST http://127.0.0.1:8787/admin/inject \
  -H 'Content-Type: application/json' \
  -d '{"kind": "queue_threshold", "queue_code": "海07"}'

# 3) 想直接叫号（"请就座"），把它钉成 called → 触发 queue.called
curl -s -X POST http://127.0.0.1:8787/admin/inject \
  -H 'Content-Type: application/json' \
  -d '{"kind": "queue_called", "queue_code": "海07"}'
```

> 也可以不手动钉：取号后只要时钟在跑（建议先 `time_scale=30`），后台 tick 会自己把 `ahead` 递减，
> 跨过阈值 5 时自动 push `queue.threshold`，归 0 时自动 `queue.called`——这才是"世界自己活着"的最佳展示。
> `/admin/inject` 是给现场"必须现在就发生"的兜底。

### 4.4 一定触发「下雨 + 全套联动」（E6 连锁，最出彩）

```bash
# 立刻下雨并锁定（code=61），一条命令引发连锁
curl -s -X POST http://127.0.0.1:8787/admin/inject \
  -H 'Content-Type: application/json' \
  -d '{"kind": "rain"}'
```

随后轮询 `GET /events?since=0` 会**依次**看到连锁事件：
1. `weather.changed`（开始下雨）
2. `venue.closed`（户外公园因雨关闭/降权）
3. `mobility.surge`（打车加价 1.5x）
4. 紧接着热门店更易 `restaurant.full`（雨天到店需求 ×1.4，排队涨更快）

验证联动是"世界真实状态改变"而非话术：
```bash
curl -s "http://127.0.0.1:8787/weather"                       # current.weather_code=61, is_raining=true
curl -s "http://127.0.0.1:8787/entertainment?type=park"       # 公园 isOpenNow=false / weatherDemoted=true
curl -s "http://127.0.0.1:8787/mobility/plan?from=望京&to=三里屯"  # taxi surge=1.5、ETA 变长、weatherNote
```

恢复晴天（复位全部联动）：

```bash
curl -s -X POST http://127.0.0.1:8787/admin/inject \
  -H 'Content-Type: application/json' -d '{"kind": "clear"}'
```

### 4.5 其他常用控场招式

```bash
# 让某店立刻剩 N 桌（放出座位，触发 restaurant.has_seat）
curl -s -X POST http://127.0.0.1:8787/admin/inject -H 'Content-Type: application/json' \
  -d '{"kind": "restaurant_seats", "restaurant_id": "r003", "seats": 5}'

# 让某店排队立刻涨到 N 桌（触发 restaurant.queue_surge）
curl -s -X POST http://127.0.0.1:8787/admin/inject -H 'Content-Type: application/json' \
  -d '{"kind": "queue_surge", "restaurant_id": "r004", "waiting": 15}'

# 让某娱乐场所立刻关闭（触发 venue.closed）
curl -s -X POST http://127.0.0.1:8787/admin/inject -H 'Content-Type: application/json' \
  -d '{"kind": "venue_closed", "venue_id": "e007"}'

# 看世界全局快照（debug 用，看每个店当前 seats_free / queue_waiting / 活跃排队）
curl -s http://127.0.0.1:8787/admin/state

# 一键复位，便于反复演示（可带 seed 复现同一随机世界）
curl -s -X POST http://127.0.0.1:8787/admin/reset -H 'Content-Type: application/json' -d '{"seed": 42}'
```

### 4.6 推荐的现场叙事顺序（≈90 秒讲完一条完整故事）

1. `POST /admin/clock {"time_scale":30}` —— "我先把世界提速 30 倍。"
2. `GET /restaurants?area=望京&sort=wait` —— "现在望京这几家有位、排队短。"
3. `POST /admin/inject {"kind":"rain"}` —— "突然下雨了。"
4. 轮询 `GET /events?since=0` —— "看，世界自己连锁反应：公园关了 → 打车加价 → 热门店开始满座。"
5. `POST /queue/take {...r004}` → 轮询 `GET /queue/status` —— "我帮你在海底捞取了号，后台在自己推进排队……剩 5 桌了，管家该提醒你了。"
6. `GET /mobility/plan?from=望京&to=三里屯` —— "雨天打车贵了、ETA 长了，所以我给你推地铁。"
7. `POST /admin/reset` —— "一键复位，可以再演一遍。"

---

## 5. 现有 skill 如何切到本后端（零改造换数据源）

每个 skill 当前是 `loadData()` 读本地 JSON。切换后只把 `loadData()` 换成
`fetch http://127.0.0.1:8787/...`，**响应里它已读取的字段名全部保持不变**，业务逻辑不用动。

| skill | 现状（读什么）| 切换后调哪个端点 | 数据字段对应（兼容点）|
|---|---|---|---|
| **food-guide** / `search-restaurants.js` | 读 `mock-restaurants.json.restaurants[]` | `GET /restaurants?area=&cuisine=&budget=&people=&sort=&limit=` | 直接吐 `{restaurants:[...]}`，每个对象含 `id/name/cuisine/area/address/rating/pricePerPerson/tags/openHours/phone/highlights` + **`waitInfo.currentWait` / `waitInfo.avgWaitMinutes`**（后台实时派生）。新增 `seatsFree/isFull` 动态字段，旧 skill 忽略即可 |
| **food-guide** / `queue-number.js` | 本地 `state.json` 自己模拟 | `POST /queue/take` → `GET /queue/status` → `POST /queue/cancel` | take 返回 `queue_code/restaurant/address/table_type/table_type_label/people/ahead/eta_min/status/estimated_call_time/tips`；status 返回 `queue_code/status/ahead/eta_min/status_text`。**演化改由后台 tick 主动做**（ahead/eta 递减、概率叫号/取消），skill 把本地 `simulateQueue` 换成"调 `/queue/status`"即可 |
| **entertainment-scout** / `discover-entertainment.js` | 读 `mock-entertainment.json.venues[]` | `GET /entertainment?area=&type=&time=&budget=&people=&mood=&limit=` | 吐 `{venues:[...]}`，含 `shows/packages/themes/classes/tonightEvent/highlights`。**密室/剧本杀主题字段保持 `name`**，并冗余别名 `themeName`（值相同，两种读法都成立）。`fitness.classes[].spotsLeft` 会随后台演化变化。新增 `isOpenNow/isOutdoor/weatherDemoted/weatherNote` 动态字段（雨天联动），旧 skill 忽略即可 |
| **mobility-planner** / `plan-route.js` | 读 `mock-areas.json` 本地算 | `GET /mobility/areas`（取配置）+ `GET /mobility/plan?from=&to=&time=&mode=` | `/areas` 原样吐 `areas/subwayConfig/taxiConfig/walkConfig`（结构与现有完全一致，本地算法可继续跑）；`/plan` 已在沙盒侧算好 `plans[]`（每项 `mode/duration/durationMinutes/cost/costValue/route/transfers/arrivalTime/pros/cons`），**且已含雨天 surge/ETA 联动**。`taxiConfig.currentSurge` 为新增动态字段（雨=1.5/晴=1.0）|
| **weather** | 直连 open-meteo | `GET /weather?area=`（或 `lat/lon`）| 严格仿 open-meteo：`current{temperature_2m, apparent_temperature, relative_humidity_2m, wind_speed_10m, weather_code}` + `daily{time, temperature_2m_max, temperature_2m_min, weather_code}`。字段名逐一对齐，直接替换 open-meteo URL 即可。`is_raining` 为冗余便利字段 |
| **管家心跳**（任务③）| 无 / 轮询本地 | `GET /events?since=<lastSeq>` | 增量取 `seq > since` 的事件，处理后把 `state.lastSeq = resp.latest_seq`。`seq` 单调严格递增、全局唯一，是**幂等去重主键**；按 `type` 分发动作（`queue.threshold`→提醒、`queue.called`→通知就座、`restaurant.full`→改荐、`weather.changed`→重排室内娱乐 + 改出行）|

> 设计取舍：餐厅/娱乐**既给整表端点**（`GET /restaurants`、`GET /entertainment`，skill 可像读 JSON 一样自己筛）
> **也给带 query 的筛选**（省得 skill 改逻辑）。两种都支持，skill 选最省改的那种。

---

## 6. demo_client.py：一键讲故事

[`demo_client.py`](./demo_client.py) 是一个**独立**演示脚本（仅依赖 Python 标准库 `urllib`，无需额外安装），
顺序调用关键端点，把世界"活着"演给评委看。一条完整故事线：

```
加速时钟 → 搜餐厅(看当前有位) → 取号 → 注入下雨 → 轮询事件流(看连锁:公园关/打车涨/餐厅满)
        → 轮询排队进度(看 ahead 递减到剩 N 桌 / 叫号) → 查出行 ETA(看雨天变化) → 一键复位
```

运行（先确保后端已在 8787 启动）：

```bash
cd dynamic-sandbox && python3 demo_client.py
```

可选参数：

```bash
# 指定后端地址（默认 http://127.0.0.1:8787）
python3 demo_client.py --base http://127.0.0.1:8787

# 调世界倍速（默认 30）
python3 demo_client.py --scale 60

# 跳过最后的 reset（想保留演示后的世界状态去 /docs 里继续看）
python3 demo_client.py --no-reset
```

脚本会带中文旁白逐步打印每个端点的关键字段，并轮询展示"排队 ahead 在递减"和"事件流在增长"，
让评委直观看到**世界是后台自己在演化的**。

---

## 7. 目录结构

```
dynamic-sandbox/
├── run.sh                # 启动脚本（单 worker，端口 8787，无 --reload）
├── requirements.txt      # 依赖留痕（版本下限）
├── README.md             # 本文件
├── demo_client.py        # 独立演示脚本（标准库实现）
├── .gitignore
├── SANDBOX_SPEC.md       # 架构/状态机/事件引擎/并发契约
├── API.md                # 逐端点 method+path+query/body+响应示例
└── app/                  # 后端代码（由 core/api agent 实现，本说明不改动）
    ├── main.py           # FastAPI 实例 + lifespan 启动时钟 + 注册 7 router + CORS
    ├── config.py         # 全局可调旋钮（tick/倍速/概率/联动系数/区域名单/出行配置）
    ├── models.py         # pydantic v2：所有 API 出入参模型
    ├── world/            # state.py / seed.py / clock.py / events.py（活的世界）
    └── routers/          # restaurants / queue / weather / mobility / entertainment / events / admin
```

---

## 8. 常见问题（FAQ）

- **`tick_count` 一直是 0？** 说明后台时钟没起来。确认是单进程启动、没用 `--reload`；看启动日志有无异常。
- **改了 `time_scale` 没感觉变化？** `/admin/clock` 改的是世界倍速，效果体现在"单位真实时间内世界推进多少"。配合轮询 `/` 看 `sim_now` 跳得更快。
- **演示砸了想重来？** `POST /admin/reset`（可带 `{"seed":42}` 复现同一世界）。
- **想复盘同一套随机演化？** 启动后立刻 `POST /admin/reset {"seed":42}`，相同 seed → 相同随机序列。
- **端口被占？** 先 `lsof -i :8787` 看谁占了；本沙盒固定 8787（已确认空闲）。
- **浏览器里跨域 fetch 不通？** 后端已开全量 CORS（`allow_origins=["*"]`），直接 fetch 即可。
