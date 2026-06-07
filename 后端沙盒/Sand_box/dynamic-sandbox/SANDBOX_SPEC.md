# 全天候私人管家 · 动态模拟沙盒后端 —— 技术契约 (SANDBOX_SPEC)

> 美团黑客松 · 任务④「自建动态 Mock 后端」+ 任务③「7×24 主动协同」基座
> 单进程 FastAPI 沙盒：一个内存世界 `WorldState`，由后台 asyncio 时钟主动演化，
> HTTP 路由层只读写世界、绝不自己算时间漂移。
> 下游有不同 agent 分别实现 `core` 与 `api`，本文件 + `API.md` 是它们之间唯一的对齐契约。

---

## 0. 运行环境 (已核实)

| 项 | 值 |
|---|---|
| Python | 3.13.5 (anaconda)，命令一律 `python3` |
| Web 框架 | FastAPI 0.115.9 (全局已装) |
| ASGI 服务器 | uvicorn 0.34.2 (全局已装) |
| pydantic | 2.10.3 (v2 语法) |
| venv | 不需要，直接全局跑 |
| 端口 | **8787** (已确认空闲) |
| 目录 | `Jensen_Song/dynamic-sandbox/`（仓库内相对路径） |

启动命令 (写进 `run.sh`)：

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --no-access-log
```

> 注意：**不要用 `--reload`**。`--reload` 会用多 worker / 子进程重载，导致后台时钟跑在被频繁杀死的子进程里、内存世界丢失。本沙盒是有状态单进程，必须单 worker。

---

## 1. 设计目标与赛题映射

| 赛题要求 | 本沙盒落地点 |
|---|---|
| **E1** 自建 FastAPI Mock 后端 | `app/main.py` + 7 个 router |
| **E2** 后台时钟/状态机主动演化 (非查询时才算) | `app/world/clock.py` 的 `world_clock_loop()` 由 `lifespan` 在 startup 拉起，每 ~5s 真实时间一个 tick，主动改 `WorldState` |
| **E3** 非静态 JSON，可复现「10 分钟内从有位→已满」 | `Restaurant.seats_free` 随机游走 + 概率涨满；tick 间隔 × `time_scale` 可加速 |
| **E4** 演化带随机性 (随机游走/概率翻台/概率涨满) | `app/world/events.py` 的演化算子全部基于 `world.rng` (可设种子) |
| **E5** 接口覆盖 skill 全部数据 | restaurants / queue / weather / mobility / entertainment 五大 router |
| **E6** [加分] 多类数据联动 | `apply_weather_linkage()`：下雨→排队变长 + 室外娱乐降权/关闭 + 打车需求与费用上升 + ETA 变长 |
| **E7** [加分] 演示控场 | `app/routers/admin.py`：`inject` 注入剧情、`clock` 改时间倍速、`reset` 重置、`state` 看全局 |
| **任务③** 7×24 主动协同事件流 | `app/routers/events.py` 的 `GET /events?since=`，每条事件带单调递增 `seq` + 唯一 `id` 幂等去重 |

核心原则一句话：**数据是「活」的——不是用户来查时才临时算一个随机数，而是后台有一个真实在跑的世界，用户只是在某个时刻去观测它。**

---

## 2. 技术选型

- **单进程 + 单 worker uvicorn**：世界状态在进程内存，多 worker 会各自持有一份世界、互相打架。
- **asyncio 后台任务 (不是 threading)**：FastAPI 原生 async；时钟用 `asyncio.create_task` 在 `lifespan` 启动，`asyncio.sleep(tick_seconds)` 驱动。整个应用是单事件循环，**不会有真正的线程并发**，但仍用一把锁守护「一个 tick 的演化」与「一次请求的读写」之间的临界区，避免请求在 tick 半途读到撕裂状态。
- **锁的选择**：`asyncio.Lock`。所有对 `WorldState` 的成组读写都在 `async with world.lock:` 内完成。tick 演化整体在锁内执行；路由处理器中凡是「读多个字段拼一个响应」或「写状态」都进锁。单字段只读可不进锁 (GIL 保证原子)。
- **pydantic v2 BaseModel**：仅用于 **API 出入参的校验与序列化**（`models.py`）。**世界内部状态用 `@dataclass`**（`world/state.py`），因为内部要频繁原地改字段、不希望每 tick 触发 pydantic 校验开销。出口时由 router 把 dataclass 投影成 dict / pydantic 模型。
- **不引入数据库 / redis**：全内存，重启即重置 (符合 demo 诉求；要持久化可选 `admin/snapshot`，非必须)。
- **时间模型**：世界有自己的「世界时钟」`world.sim_now`(datetime)。真实过去 `tick_seconds` 秒，世界时间前进 `tick_seconds * time_scale` 秒。`time_scale` 默认 1.0；demo 时调到 20~60，让 10 分钟演化在 30 秒内看到 (E7)。**路由层永远读 `world.sim_now`，绝不自己 `datetime.now()` 算漂移**（这是契约硬约束，否则两个 agent 的时间会对不齐）。

---

## 3. 目录与文件清单

```
dynamic-sandbox/
├── run.sh                      # 启动脚本 (uvicorn 单 worker, 端口 8787)
├── SANDBOX_SPEC.md             # 本文件：架构/状态机/事件引擎/契约
├── API.md                      # 逐端点 method+path+query/body+响应示例
├── requirements.txt            # 记录版本 (fastapi==0.115.9 等)，环境已装，仅留痕
└── app/
    ├── __init__.py
    ├── main.py                 # FastAPI 实例 + lifespan 启动时钟 + 注册 7 router + CORS
    ├── config.py               # 全局配置常量 (端口/tick/倍速/概率/联动系数/区域名单)
    ├── models.py               # pydantic v2: 所有 API 出入参模型
    ├── world/
    │   ├── __init__.py
    │   ├── state.py            # WorldState + 各实体 dataclass + 全局单例 world
    │   ├── seed.py             # 初始化世界 (15 区域 / 餐厅 / 娱乐 / 天气 / 出行配置)
    │   ├── clock.py            # 后台时钟循环 world_clock_loop() + tick()
    │   └── events.py           # 演化算子 + 随机事件 + 联动 + 事件流 push
    └── routers/
        ├── __init__.py
        ├── restaurants.py      # router 变量名: router  | prefix /restaurants
        ├── queue.py            # router 变量名: router  | prefix /queue
        ├── weather.py          # router 变量名: router  | prefix /weather
        ├── mobility.py         # router 变量名: router  | prefix /mobility
        ├── entertainment.py    # router 变量名: router  | prefix /entertainment
        ├── events.py           # router 变量名: router  | prefix /events
        └── admin.py            # router 变量名: router  | prefix /admin
```

> **契约约定**：每个 router 模块都导出一个名为 `router` 的 `APIRouter`，`prefix` 在该模块内用 `APIRouter(prefix=..., tags=...)` 设定；`main.py` 统一 `app.include_router(<module>.router)`。下游实现 api 的 agent 必须遵守模块名 + `router` 变量名 + prefix。

---

## 4. 数据模型 (世界内部 dataclass，`app/world/state.py`)

> 内部用 dataclass；字段命名尽量贴近现有 skill JSON 的 **camelCase 出口字段**，但内部演化变量用 snake_case 以区分（出口时映射）。每个实体都额外带演化所需的「隐藏状态」(capacity / seats_free / turnover 等)，这些隐藏状态**不一定出现在对外响应**，只为驱动 `waitInfo` 等可见字段。

### 4.1 Restaurant (餐厅)

```python
@dataclass
class Restaurant:
    # —— 对外可见 (贴合现有 mock-restaurants.json schema) ——
    id: str                      # "r001"
    name: str
    cuisine: str
    area: str                    # 必属于 config.AREAS
    address: str
    rating: float
    pricePerPerson: int
    tags: list[str]
    openHours: str               # "11:30-14:00, 17:00-22:00"
    phone: str
    highlights: list[str]
    shows: list[dict] | None = None   # 餐厅一般 None；保留字段兼容 schema
    # —— 隐藏演化状态 (驱动 waitInfo) ——
    capacity: int = 40           # 总桌数
    seats_free: int = 10         # 空桌数 (0 = 已满)；随机游走的主变量
    queue_waiting: int = 0       # 当前排队桌数 = waitInfo.currentWait
    turnover_min_per_table: float = 8.0  # 每桌翻台耗时(分钟)，决定 avgWaitMinutes
    is_full: bool = False        # seats_free==0 时为 True
    base_popularity: float = 0.5 # 0~1，热门度，影响涨满概率
    # waitInfo 是「派生」字段：
    #   waitInfo.currentWait   = queue_waiting
    #   waitInfo.avgWaitMinutes= round(queue_waiting * turnover_min_per_table)
```

对外响应里的 `waitInfo` 由 `restaurants.py` 在出口处计算：`{"currentWait": queue_waiting, "avgWaitMinutes": round(queue_waiting * turnover_min_per_table)}`。

### 4.2 Venue (娱乐场所)

```python
@dataclass
class Venue:
    id: str                      # "e001"
    name: str
    type: str                    # movie|bar|ktv|escape_room|board_game|park|fitness|spa|massage|billiards|shopping
    typeLabel: str               # "🎬 电影" 等 (沿用现有 emoji 标签)
    area: str
    address: str
    rating: float
    priceRange: str              # "150-300" | "免费（逛街）" | "¥5（门票）"
    openHours: str
    tags: list[str]
    # —— 按 type 可选结构 (字段名严格沿用现有 mock-entertainment.json) ——
    shows: list[dict] | None = None      # movie:  [{movie,time,endTime,price,hall,rating}]
    packages: list[dict] | None = None   # ktv:    [{name,capacity,price,period}]
    themes: list[dict] | None = None     # escape_room/board_game: [{name,difficulty,duration,players,price,genre,availableSlots[]}]
    classes: list[dict] | None = None    # fitness:[{name,time,duration,price,spotsLeft}]
    highlights: list[str] | None = None
    tonightEvent: dict | None = None     # bar: {name,time,coverCharge}
    # —— 隐藏演化状态 ——
    is_outdoor: bool = False     # park 等户外；下雨联动关闭/降权的判定
    is_open_now: bool = True     # 受 openHours + 天气联动影响
    weather_demoted: bool = False# 因天气被降权 (rank 时排后/打标)
    rating_effective: float = 0.0# 联动后的有效评分 (= rating，下雨时户外 -0.5 等)
```

> **兼容性关键点**：现有 `mock-entertainment.json` 里密室/剧本杀的主题字段是 `name`（不是 prompt 描述的 `themeName`）、难度是星号串 `difficulty`（如 `"⭐⭐⭐⭐"`）。本沙盒**严格沿用现有 JSON 的字段名 `name`**，并**额外冗余一个 `themeName` 别名**（值相同），让两种读法都成立、skill 零改造。`fitness.classes` 沿用现有 `{name,time,duration,price,spotsLeft}`，其中 `spotsLeft` 是可演化的隐藏可见量。

### 4.3 Area / 出行配置 (`areas`)

```python
@dataclass
class Station:
    name: str
    lines: list[str]

@dataclass
class Area:
    name: str
    lat: float
    lon: float
    stations: list[Station]

# subwayConfig / taxiConfig / walkConfig 直接以现有 mock-areas.json 的结构
# 作为模块级常量存放 (见 config.py)，出行 router 原样吐出 + 叠加动态字段。
```

15 个区域（与现有一致，缺的补全）：`798 望京 三里屯 朝阳大悦城 国贸 中关村 五道口 朝阳公园 簋街 前门 西单 王府井 交通大学 国际会议中心 国家会议中心`。

### 4.4 Weather (天气，仿 open-meteo)

```python
@dataclass
class WeatherState:
    temperature: float           # current.temperature_2m
    apparent_temperature: float  # current.apparent_temperature
    humidity: int                # current.relative_humidity_2m
    wind_speed: float            # current.wind_speed_10m
    weather_code: int            # 0晴 / 1,2,3 多云阴 / 61,63,65 小中大雨 / 80,81,82 阵雨 / 95 雷暴 ...
    is_raining: bool             # 派生：code in {51,53,55,61,63,65,80,81,82,95,96,99}
    daily: list[dict]            # 长度3: [{date, max, min, code}]
    trend: str = "stable"        # warming|cooling|stable，给随机游走方向
```

天气对外按 open-meteo 形态输出 (见 `API.md` /weather)。

### 4.5 QueueTicket (排队票)

```python
@dataclass
class QueueTicket:
    queue_code: str              # "金01" = 餐厅首字 + 两位序号
    restaurant_id: str
    restaurant_name: str
    address: str
    table_type: str              # "small"|"medium"|"large"
    table_type_label: str        # "小桌（1-2人）"
    people: int
    customer_name: str
    status: str                  # waiting|called|seated|cancelled
    taken_at: datetime           # = world.sim_now (世界时间)
    ahead: int                   # 前面还有几桌 (被 tick 主动递减)
    eta_min: int                 # 预计等待分钟 (= ahead * turnover, 被 tick 刷新)
    called_at: datetime | None = None
    seated_at: datetime | None = None
    cancelled_at: datetime | None = None
```

> **与现有 queue-number.js 的对齐**：现有 skill 是「无后台进程、查询时按流逝时间算」。切到本沙盒后，**演化由后台 tick 主动做**（ahead/eta 在 tick 里递减、概率叫号、概率取消），skill 只需把本地 `simulateQueue` 换成「调 `GET /queue/status`」。响应字段对齐：`queue_code / status / ahead / eta_min / status_text` + 现有 skill 已读的 `restaurant / address / tableType / people`。

### 4.6 WorldEvent (世界事件，喂事件流)

```python
@dataclass
class WorldEvent:
    seq: int                     # 单调递增，全局唯一，幂等去重主键
    id: str                      # "evt-000123" (= f"evt-{seq:06d}")，二次幂等线索
    type: str                    # 见 §7 事件类型表
    sim_time: str                # 世界时间 ISO，事件发生的世界时刻
    real_time: str               # 真实墙钟 ISO，便于 demo 对时
    subject: dict                # 关联实体快照 {kind, id, name, area, ...}
    payload: dict                # 事件细节 (如 {seats_free:0} / {ahead:5} / {weather_code:61})
    message: str                 # 人类可读，可直接展示给用户
    severity: str = "info"       # info|notice|alert
```

### 4.7 WorldState (世界总状态，单例)

```python
@dataclass
class WorldState:
    lock: asyncio.Lock
    rng: random.Random           # 可 seed，保证「随机但可复盘」
    sim_now: datetime            # 世界时钟当前时刻
    time_scale: float            # 世界倍速 (E7 加速)
    tick_seconds: float          # 真实多少秒一个 tick
    tick_count: int              # 已 tick 次数 (心跳/调试)
    paused: bool                 # 是否暂停演化 (admin 可控)
    restaurants: dict[str, Restaurant]
    venues: dict[str, Venue]
    areas: dict[str, Area]
    weather: WeatherState
    queue: dict[str, QueueTicket]      # key = queue_code
    next_seq_per_rest: dict[str, int]  # 取号序号
    events: list[WorldEvent]           # 事件日志 (环形截断，留最近 N 条)
    event_seq: int                     # 事件全局序号游标
    scripted_overrides: dict           # admin inject 留下的「钉死/偏置」标记
```

`app/world/state.py` 末尾导出全局单例：`world: WorldState`（由 `seed.build_world()` 构造）。所有模块 `from app.world.state import world` 共享同一对象。

---

## 5. 世界状态机 (餐厅 / 排队 / 天气 的状态转移)

### 5.1 餐厅座位状态机 (E3 的核心)

每个餐厅在每 tick 经历：随机游走 → 概率事件 → 派生可见字段。

```
状态量: seats_free ∈ [0, capacity], queue_waiting ≥ 0, is_full
─────────────────────────────────────────────────────────────
每 tick (世界时间前进 Δ = tick_seconds * time_scale 秒):
  1) 翻台释放: 期望释放桌数 = Δ秒 / (turnover_min*60) * 正在用餐桌数比例
     → seats_free += poisson_like(rng)   (取整, 不超过 capacity)
  2) 到店占座: 到店强度 λ = base_popularity * 餐时段权重(meal_window) * 天气系数
     → 新到 newcomers = rng 抽样(λ)
     → 若 seats_free>0: 先坐下 min(seats_free, newcomers)，seats_free 减
     → 余下的人进排队: queue_waiting += 剩余
  3) 概率涨满: 若 seats_free 较低且热门, 以 p_full 概率直接 seats_free=0 (E4 概率翻满)
  4) 排队消化: 若 seats_free>0 且 queue_waiting>0: 入座 min(...)，两边同减
  5) 派生: is_full = (seats_free==0)
           waitInfo.currentWait = queue_waiting
           waitInfo.avgWaitMinutes = round(queue_waiting * turnover_min_per_table)
  6) 触发事件 (见 §7): seats_free 跨 0 边界 → restaurant.full / restaurant.has_seat
─────────────────────────────────────────────────────────────
```

「10 分钟内从有位→已满」复现：热门餐厅 `base_popularity` 高 + 处于餐时段 + (可选) 下雨联动，到店强度 > 翻台速度，`seats_free` 单调走低，在若干 tick 内归零并触发 `restaurant.full` 事件。配合 `time_scale=20`，真实 30 秒看完 10 分钟世界演化 (E7)。

### 5.2 排队票状态机

```
waiting ──(ahead 递减到 0, 由 tick 主动推进)──▶ called ──(超时/被领位)──▶ seated
   │                                              │
   │（每 tick 概率 p_cancel 放弃）                  │（called 超 T 分钟未就座, 概率自动 seated 或保持）
   ▼                                              ▼
cancelled                                       seated
```

- 每 tick：对所有 `waiting` 票，`ahead = max(0, ahead - served_this_tick)`（served 由该餐厅翻台速度算），`eta_min = round(ahead * turnover)`。
- `ahead==0` → `status=called`，记 `called_at=sim_now`，**push 事件 `queue.called`**。
- 每 tick 对 `waiting` 票以 `p_cancel`(默认 ~0.12/小时 折算到 tick) 概率 → `cancelled`。
- `ahead` 跨过阈值 (默认 5) 时 push `queue.threshold`（让管家「盯排队→剩5桌→提醒/叫车」，对接任务③）。

### 5.3 天气状态机 (随机游走 + 突变)

```
weather_code 在「晴(0) ↔ 多云(1,2,3) ↔ 阵雨(80,81,82) ↔ 小中大雨(61,63,65) ↔ 雷暴(95)」间转移
─────────────────────────────────────────────────────────────
每 tick (低频, 见 config.WEATHER_TICK_EVERY 个 tick 才动一次):
  - temperature: 朝 trend 方向 ±随机游走 (高斯), 夹在合理区间
  - apparent_temperature = temperature ± f(wind, humidity)
  - humidity / wind_speed: 有界随机游走
  - weather_code: 以马尔可夫转移矩阵抽样下一状态 (E4 随机)
  - is_raining 由 code 派生; 若从「不下雨」→「下雨」跨边界 → push weather.changed(severity=notice)
                                并触发 §6 联动
```

admin `inject {"kind":"rain"}` 可直接把 `weather_code` 钉到 61 并标记 `scripted_overrides["weather_locked"]`，让 demo「立刻下雨」(E7)。

---

## 6. 多类数据联动引擎 (E6 加分项) —— `apply_weather_linkage(world)`

下雨 (`weather.is_raining == True`) 时，在该 tick 末尾统一施加联动 (一处实现，多处生效)：

| 维度 | 联动效果 | 实现 |
|---|---|---|
| **餐厅排队** | 排队变长 | 该 tick 餐厅「到店强度 λ」乘 `RAIN_DEMAND_MULT`(默认 1.4)，到店多→`queue_waiting` 涨更快；并对热门店 `p_full` 提升 |
| **室外娱乐** | 关闭 / 降权 | `venue.is_outdoor` 的场所：`is_open_now=False`(park 雨天闭) 或 `weather_demoted=True`、`rating_effective -= 0.5`；entertainment 推荐排序时降权 + 打 `weatherNote` |
| **打车** | 需求 + 费用上升 | mobility 出行响应里 taxi 方案的 `surge` 系数 = `RAIN_SURGE`(默认 1.5)，`costValue`/`cost` 上浮，附 `peakWarning`/`weatherNote="雨天打车加价"` |
| **出行 ETA** | 变长 | 所有方案 (尤其 taxi) `durationMinutes *= RAIN_ETA_MULT`(默认 1.25)；subway 受影响小、walk 直接给「雨天不建议」提示 |

联动是**世界级别的真实状态改变**，不是查询时临时拼的话术：下雨后即使没人查餐厅，后台 tick 也已经让餐厅排得更满、把公园关了。用户/skill 任何时刻去观测，看到的都是「联动后」的世界。

晴天恢复：`is_raining` 转回 False 时，`apply_weather_linkage` 把户外场所 `is_open_now`/`weather_demoted` 复位、taxi surge 归 1。

---

## 7. 随机事件引擎 + 事件流 (E2/E4 + 任务③) —— `app/world/events.py`

### 7.1 事件类型表

| type | 触发条件 | severity | payload 关键字段 | message 示例 |
|---|---|---|---|---|
| `restaurant.full` | seats_free 由 >0 跨到 0 | alert | `{restaurantId, seats_free:0, area}` | 「海底捞(望京店)已满座」 |
| `restaurant.has_seat` | seats_free 由 0 跨到 >0 | notice | `{restaurantId, seats_free}` | 「太二酸菜鱼放出 3 桌」 |
| `restaurant.queue_surge` | queue_waiting 跨过 surge 阈值(默认 12) | notice | `{restaurantId, queue_waiting}` | 「绿茶餐厅排队已超 12 桌」 |
| `queue.threshold` | 某票 ahead 跨到 ≤ 阈值(默认 5) | notice | `{queue_code, ahead, eta_min, restaurantId}` | 「您的号金01前面只剩5桌」 |
| `queue.called` | 某票 ahead→0 → called | alert | `{queue_code, restaurantId}` | 「金01 已叫号，请就座」 |
| `queue.cancelled` | 票被概率放弃 | info | `{queue_code}` | — |
| `weather.changed` | is_raining 跨边界 / code 突变 | notice | `{weather_code, is_raining, temperature}` | 「望京开始下雨了」 |
| `venue.closed` | 户外场所因雨 is_open_now→False | notice | `{venueId, reason:"rain"}` | 「望京公园因降雨暂不推荐」 |
| `mobility.surge` | 打车进入加价 (雨/高峰) | notice | `{surge, reason}` | 「当前打车加价 1.5x」 |
| `demo.injected` | admin inject 触发的剧情 | info/alert | 透传 inject 内容 | 「[控场] 已将 r004 钉为满座」 |

### 7.2 事件产生与去重 (幂等线索)

- 所有事件经唯一入口 `push_event(world, type, subject, payload, message, severity)` 产生。
- 入口内：`world.event_seq += 1`；`seq = world.event_seq`；`id = f"evt-{seq:06d}"`；`sim_time=world.sim_now`；`real_time=now()`；append 到 `world.events`（超 `EVENT_LOG_MAX` 条则丢最旧）。
- **幂等去重契约**：消费方 (管家心跳) 记住「已处理到的 max seq」，下次 `GET /events?since=<seq>` 只取 `seq > since` 的事件。`seq` 单调严格递增、全局唯一，是去重主键；`id` 是同义的字符串形式，便于日志关联。同一逻辑事件不会因为「状态持续满座」每 tick 重复 push——只在**跨边界那一刻** push 一次 (用「上一 tick 值 vs 本 tick 值」比较实现边沿触发，而非电平触发)。

### 7.3 事件流端点

`GET /events?since=<seq>&limit=<n>&type=<可选过滤>` → 返回 `seq > since` 的事件数组 + `latest_seq`（方便下次传 since）。详见 `API.md`。

---

## 8. 后台时钟 (E2 核心) —— `app/world/clock.py`

### 8.1 关键函数签名 (契约，下游 core agent 必须照实现)

```python
# app/world/clock.py
import asyncio
from app.world.state import world
from app.world import events as ev

async def world_clock_loop() -> None:
    """后台主循环：被 main.lifespan 用 asyncio.create_task 拉起。
    while True: 若未暂停则 await tick(); 再 asyncio.sleep(world.tick_seconds)。
    捕获并吞掉单 tick 异常 (打日志) 以保证循环不死。"""

async def tick() -> None:
    """推进世界一个步长。整个过程持锁 (async with world.lock)。
    顺序:
      1. world.sim_now += timedelta(seconds=world.tick_seconds * world.time_scale)
      2. world.tick_count += 1
      3. ev.evolve_weather(world)              # 低频, 见 WEATHER_TICK_EVERY
      4. for r in restaurants: ev.evolve_restaurant(world, r)   # 含边沿事件
      5. ev.evolve_queue(world)                # 推进所有票, 含 called/threshold/cancel
      6. ev.apply_weather_linkage(world)       # E6 联动 (统一施加)
      7. ev.evolve_venues(world)               # 营业时间 + 天气开闭
    注: 不在这里 sleep; sleep 由 loop 负责。"""
```

### 8.2 演化算子签名 (`app/world/events.py`)

```python
def evolve_restaurant(world: WorldState, r: Restaurant) -> None: ...
def evolve_queue(world: WorldState) -> None: ...
def evolve_weather(world: WorldState) -> None: ...
def evolve_venues(world: WorldState) -> None: ...
def apply_weather_linkage(world: WorldState) -> None: ...
def push_event(world: WorldState, type: str, subject: dict,
               payload: dict, message: str, severity: str = "info") -> WorldEvent: ...

# 控场算子 (被 admin router 调用)
def inject_scenario(world: WorldState, kind: str, params: dict) -> dict: ...
#   kind: "rain" | "clear" | "restaurant_full" | "restaurant_seats" |
#         "queue_threshold" | "queue_called" | "venue_closed" | "queue_surge"
def set_clock(world: WorldState, time_scale: float | None,
              tick_seconds: float | None, paused: bool | None) -> dict: ...
def reset_world(world: WorldState, seed: int | None) -> None: ...   # 调 seed.build_world 重建
```

### 8.3 main.py 契约骨架

```python
# app/main.py
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.world.clock import world_clock_loop
from app.routers import restaurants, queue, weather, mobility, entertainment, events, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(world_clock_loop())   # 启动后台时钟 (E2)
    yield
    task.cancel()                                    # 退出时干净取消

app = FastAPI(title="全天候私人管家 · 动态沙盒", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for m in (restaurants, queue, weather, mobility, entertainment, events, admin):
    app.include_router(m.router)

@app.get("/")          # 健康检查 + 世界概览
async def root(): ...
@app.get("/health")
async def health(): ...
```

---

## 9. 配置 (`app/config.py`) —— 全部可调旋钮

```python
# 时钟
PORT = 8787
TICK_SECONDS = 5.0          # 真实 5 秒一个 tick
DEFAULT_TIME_SCALE = 1.0    # 世界倍速 (demo 调 20~60)
WEATHER_TICK_EVERY = 6      # 每 6 个 tick 演化一次天气 (≈30 真实秒)

# 餐厅演化
MEAL_WINDOWS = ["11:30-14:00", "17:00-21:30"]  # 餐时段 (按 sim_now 判定到店强度)
P_FULL = 0.12               # 低位时概率涨满
QUEUE_SURGE_THRESHOLD = 12  # 排队涨满事件阈值

# 排队
QUEUE_THRESHOLD_AHEAD = 5   # 剩 N 桌触发提醒 (任务③)
P_CANCEL_PER_HOUR = 0.12    # 排队放弃率/小时

# 天气联动 (E6)
RAIN_DEMAND_MULT = 1.4      # 雨天到店/排队需求放大
RAIN_SURGE = 1.5            # 雨天打车加价
RAIN_ETA_MULT = 1.25        # 雨天 ETA 放大
RAINY_CODES = {51,53,55,61,63,65,66,67,80,81,82,85,86,95,96,99}

# 事件流
EVENT_LOG_MAX = 500         # 环形日志上限

# 区域名单 (15)
AREAS = ["798","望京","三里屯","朝阳大悦城","国贸","中关村","五道口",
         "朝阳公园","簋街","前门","西单","王府井","交通大学",
         "国际会议中心","国家会议中心"]

# 出行配置 (原样取自 mock-areas.json)
SUBWAY_CONFIG = {...}; TAXI_CONFIG = {...}; WALK_CONFIG = {...}
```

---

## 10. 与现有 skill 的对接 (零改造切换数据源)

每个 skill 当前是 `loadData()` 读本地 JSON。切换后只把 `loadData()` 换成 `fetch http://127.0.0.1:8787/...`，**响应里它已读取的字段名都保持不变**：

| skill | 现状 | 切换后调用 | 响应兼容点 |
|---|---|---|---|
| food-guide / search-restaurants.js | 读 `mock-restaurants.json.restaurants[]` | `GET /restaurants?area=&cuisine=&budget=&people=&sort=&limit=` | 直接吐 `{restaurants:[...]}`，每个对象字段含 `waitInfo.currentWait/avgWaitMinutes` 等全字段 |
| food-guide / queue-number.js | 本地 `state.json` 模拟 | `POST /queue/take` / `GET /queue/status` / `POST /queue/cancel` | 返回 `queue_code/status/ahead/eta_min/status_text` + `restaurant/address/tableType/people` |
| entertainment-scout / discover-entertainment.js | 读 `mock-entertainment.json.venues[]` | `GET /entertainment?area=&type=&time=&budget=` | `{venues:[...]}`，含 shows/packages/themes/classes/tonightEvent，主题字段 `name`(+别名 themeName) |
| mobility-planner / plan-route.js | 读 `mock-areas.json` 本地算 | `GET /mobility/areas`(取配置) + `GET /mobility/plan?from=&to=&time=` | `areas/subwayConfig/taxiConfig/walkConfig` 结构原样；`/plan` 直接吐 `plans[]`，且已含雨天 surge |
| weather | 直连 open-meteo | `GET /weather?area=` (或 lat/lon) | 仿 open-meteo：`current{temperature_2m,...}`+`daily{...}` |

> 设计取舍：餐厅/娱乐既给「整表」端点（`GET /restaurants`、`GET /entertainment`，skill 可像读 JSON 一样自己筛），也给带 query 的筛选（省得 skill 改逻辑）。两种都支持，skill 选最省改的那种。

---

## 11. 并发与一致性约束 (硬契约)

1. **唯一时间源**：任何模块要「现在几点」一律读 `world.sim_now`。路由层禁止 `datetime.now()` 参与业务计算 (仅 `real_time` 戳记可用墙钟)。
2. **改世界必持锁**：所有写 `WorldState` 的代码 (tick、queue take/cancel、admin inject/clock/reset) 必须 `async with world.lock:`。
3. **读多字段持锁**：组装一个响应需要读「跨实体 / 多字段」时持锁，避免读到 tick 半途的撕裂状态；单字段只读可不持锁。
4. **边沿触发事件**：事件只在状态「跨边界」时 push 一次，禁止电平式每 tick 重复 push。
5. **router 契约**：模块名、`router` 变量名、prefix 必须与 §3/§4/§8 一致，core 与 api 两个 agent 据此独立实现、最终对齐。

---

## 12. Demo 脚本建议 (E7 展示路径)

1. `POST /admin/clock {"time_scale":30}` → 世界提速 30 倍。
2. `GET /restaurants?area=望京&sort=wait` → 看当前有位餐厅。
3. `POST /admin/inject {"kind":"rain"}` → 立刻下雨；几秒内 `GET /weather` 见 code=61。
4. 轮询 `GET /events?since=0` → 依次看到 `weather.changed` → `venue.closed`(公园) → `mobility.surge` → 某热门店 `restaurant.full`（E6 联动连锁）。
5. `POST /queue/take {restaurant_id:r004,people:2}` 取号 → 轮询 `GET /queue/status` → tick 推进 ahead 递减 → 收到 `queue.threshold`(剩5桌) → `queue.called`（管家据此主动提醒/叫车，任务③闭环）。
6. `POST /admin/inject {"kind":"restaurant_full","restaurant_id":"r002"}` → 立刻让 r002 满座，复现 E3。
7. `POST /admin/reset` → 一键复位，便于反复演示。
