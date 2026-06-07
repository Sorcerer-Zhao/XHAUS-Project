# -*- coding: utf-8 -*-
"""演化引擎 + 随机事件 + 多类联动 + 事件流入口 + 控场算子。

这是动态沙盒的"模拟心脏"。被 clock.tick() 每 tick 调用，主动改 WorldState：
  - evolve_restaurant: 餐厅座位随机游走 / 概率翻满 / 排队消化（含边沿事件 §7）
  - evolve_queue:      推进所有排队票（ahead 递减 / 概率叫号 / 概率取消 / 阈值提醒）
  - evolve_weather:    天气低频随机游走 + 马尔可夫转移（下雨跨边界触发事件）
  - evolve_venues:     按 openHours 判定营业 + 天气联动开闭
  - apply_weather_linkage: E6 联动统一施加（下雨→排队↑ + 户外关 + 打车↑ + ETA↑）
  - push_event:        唯一事件产生入口（seq/id 单调递增，幂等去重主键）

设计要点：
  - 所有随机性走 world.rng（可 seed → 随机但可复盘，E4）。
  - 事件用"上一 tick 值 vs 本 tick 值"做**边沿触发**，绝不电平式每 tick 重复 push（§11.4）。
  - 本模块函数都假设**调用方已持锁**（tick / admin 路由统一在 async with world.lock 内调）。
  - 唯一时间源 world.sim_now，本模块不碰 datetime.now()（real_time 戳记除外）。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from app import config
from app.world.state import (
    QueueTicket,
    Restaurant,
    WorldEvent,
    WorldState,
)


# ════════════════════════ 事件产生（唯一入口） ════════════════════════

def push_event(world: WorldState, type: str, subject: dict,
               payload: dict, message: str, severity: str = "info") -> WorldEvent:
    """产生一条世界事件，写入环形日志。返回该事件对象。

    幂等线索：seq 单调严格递增、全局唯一；id = f"evt-{seq:06d}" 为其字符串别名。
    消费方（管家心跳）记住已处理的 max seq，下次 GET /events?since=<seq> 即去重。
    """
    world.event_seq += 1
    seq = world.event_seq
    evt = WorldEvent(
        seq=seq,
        id=f"evt-{seq:06d}",
        type=type,
        sim_time=world.sim_iso(),
        real_time=datetime.now().replace(microsecond=0).isoformat(),  # 真实墙钟仅供对时
        subject=subject,
        payload=payload,
        message=message,
        severity=severity,
    )
    world.events.append(evt)
    # 环形截断：超上限丢最旧
    if len(world.events) > config.EVENT_LOG_MAX:
        del world.events[: len(world.events) - config.EVENT_LOG_MAX]
    return evt


# ════════════════════════ 随机抽样工具 ════════════════════════

def _poisson(world: WorldState, lam: float) -> int:
    """泊松抽样（Knuth 算法）。lam 很小/为 0 时直接返回 0。"""
    if lam <= 0:
        return 0
    if lam > 30:  # 大 lam 用正态近似，避免循环过久
        val = world.rng.gauss(lam, math.sqrt(lam))
        return max(0, round(val))
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= world.rng.random()
        if p <= L:
            return k - 1


def _meal_boost(world: WorldState) -> float:
    """按 sim_now 是否处于餐时段，给到店强度乘数。"""
    hhmm = world.sim_now.strftime("%H:%M")
    if WorldState._in_window(hhmm, config.MEAL_WINDOWS):
        return config.MEAL_DEMAND_BOOST
    return config.OFFPEAK_DEMAND


def _open_now(world: WorldState, open_hours: str) -> bool:
    """按 openHours 字符串判定当前世界时刻是否营业。

    支持形如 "11:30-14:00, 17:00-22:00" / "10:00-次日07:00" / "06:00-22:00"。
    含"次日"按跨午夜处理。
    """
    hhmm = world.sim_now.strftime("%H:%M")

    def to_min(s: str) -> int:
        s = s.replace("次日", "").strip()
        h, m = s.split(":")
        return int(h) * 60 + int(m)

    cur = to_min(hhmm)
    for seg in open_hours.split(","):
        seg = seg.strip()
        if "-" not in seg:
            continue
        a, b = seg.split("-")
        cross = "次日" in b
        am, bm = to_min(a), to_min(b)
        if cross:  # 跨午夜，b 实际是次日
            if cur >= am or cur <= bm:
                return True
        else:
            if am <= cur <= bm:
                return True
    return False


# ════════════════════════ 餐厅演化（E3 核心） ════════════════════════

def evolve_restaurant(world: WorldState, r: Restaurant) -> None:
    """推进单个餐厅一个 tick：翻台释放 → 到店占座 → 概率涨满 → 排队消化 → 派生 → 边沿事件。"""
    # 被 admin 钉死的餐厅本 tick 不自然演化（控场优先）
    if r.id in world.scripted_overrides.get("locked_restaurants", set()):
        return
    if r.temporarily_closed or r.id in world.scripted_overrides.get("closed_restaurants", set()):
        return

    dt_min = world.tick_minutes()
    if dt_min <= 0:
        return

    prev_seats_free = r.seats_free
    prev_queue = r.queue_waiting

    # 餐厅未营业：缓慢清空排队，不再到店
    if not _open_now(world, r.openHours):
        if r.queue_waiting > 0:
            r.queue_waiting = max(0, r.queue_waiting - _poisson(world, dt_min / 5.0))
        r.seats_free = min(r.capacity, r.seats_free + _poisson(world, dt_min / r.turnover_min_per_table))
        r.is_full = r.seats_free == 0
        _emit_restaurant_edges(world, r, prev_seats_free, prev_queue)
        return

    # 1) 翻台释放：占用桌数 / turnover 决定每分钟释放速率（带小数累积，避免取整抹平）
    occupied = r.capacity - r.seats_free
    release_rate = occupied / max(1.0, r.turnover_min_per_table) * config.TURNOVER_RELEASE_RATIO
    r._release_carry += release_rate * dt_min
    released = int(r._release_carry)
    if released > 0:
        r._release_carry -= released
        r.seats_free = min(r.capacity, r.seats_free + released)

    # 2) 到店强度 λ = 基础 × 热门度 × 餐时段权重 × 天气系数 × 本tick分钟
    weather_mult = config.RAIN_DEMAND_MULT if world.weather.is_raining else 1.0
    lam = (config.ARRIVAL_BASE_PER_MIN * (0.4 + r.base_popularity)
           * _meal_boost(world) * weather_mult * dt_min)
    newcomers = _poisson(world, lam)
    if newcomers > 0:
        if r.seats_free > 0:
            seated = min(r.seats_free, newcomers)
            r.seats_free -= seated
            newcomers -= seated
        # 余下的人进排队
        if newcomers > 0:
            r.queue_waiting += newcomers

    # 3) 概率涨满：座位低位且热门 → 以 p_full 概率直接满座（E4 概率翻满）
    if 0 < r.seats_free <= config.P_FULL_LOW_SEATS:
        p_full = config.P_FULL * (0.5 + r.base_popularity)
        if world.weather.is_raining:
            p_full *= config.RAIN_PFULL_BOOST
        if world.rng.random() < min(0.95, p_full):
            # 没坐下的人去排队
            r.queue_waiting += r.seats_free
            r.seats_free = 0

    # 4) 排队消化：有空位且有人排队 → 入座
    if r.seats_free > 0 and r.queue_waiting > 0:
        served = min(r.seats_free, r.queue_waiting)
        r.seats_free -= served
        r.queue_waiting -= served

    # 5) 派生可见字段
    r.is_full = r.seats_free == 0

    # 6) 边沿事件
    _emit_restaurant_edges(world, r, prev_seats_free, prev_queue)


def _emit_restaurant_edges(world: WorldState, r: Restaurant,
                           prev_seats_free: int, prev_queue: int) -> None:
    """根据"上一 tick vs 本 tick"做边沿触发，避免电平式重复 push。"""
    subj = {"kind": "restaurant", "id": r.id, "name": r.name, "area": r.area}

    # seats_free 由 >0 跨到 0 → 满座
    if prev_seats_free > 0 and r.seats_free == 0:
        push_event(world, "restaurant.full", subj,
                   {"restaurantId": r.id, "seats_free": 0, "area": r.area,
                    "queue_waiting": r.queue_waiting},
                   f"🍲 {r.name}已满座，当前排队 {r.queue_waiting} 桌",
                   severity="alert")
    # seats_free 由 0 跨到 >0 → 放出座位
    elif prev_seats_free == 0 and r.seats_free > 0:
        push_event(world, "restaurant.has_seat", subj,
                   {"restaurantId": r.id, "seats_free": r.seats_free, "area": r.area},
                   f"🪑 {r.name}放出 {r.seats_free} 桌，现在可以去了",
                   severity="notice")

    # 排队跨过 surge 阈值（由下往上跨）→ 排队涨满
    th = config.QUEUE_SURGE_THRESHOLD
    if prev_queue <= th < r.queue_waiting:
        push_event(world, "restaurant.queue_surge", subj,
                   {"restaurantId": r.id, "queue_waiting": r.queue_waiting, "area": r.area},
                   f"🔥 {r.name}排队已超 {th} 桌（当前 {r.queue_waiting} 桌）",
                   severity="notice")


# ════════════════════════ 排队票演化 ════════════════════════

def evolve_queue(world: WorldState) -> None:
    """推进所有排队票：ahead 递减 → 阈值提醒 → 到 0 叫号 → 概率取消 → 清理过期票。"""
    dt_min = world.tick_minutes()
    if dt_min <= 0:
        return

    to_delete: list[str] = []
    for code, t in world.queue.items():
        if t.status in ("seated", "cancelled"):
            # 过期清理（保留一段时间供查询）
            ref = t.seated_at or t.cancelled_at or t.taken_at
            if (world.sim_now - ref).total_seconds() / 60.0 > config.QUEUE_TICKET_TTL_MIN:
                to_delete.append(code)
            continue

        r = world.restaurants.get(t.restaurant_id)
        turnover = r.turnover_min_per_table if r else 8.0

        if t.status == "called":
            # 已叫号：一段时间后概率自动入座（视为顾客已就座）
            if t.called_at and (world.sim_now - t.called_at).total_seconds() / 60.0 > 8:
                if world.rng.random() < 0.5:
                    t.status = "seated"
                    t.seated_at = world.sim_now
            continue

        # waiting：先按概率取消（被该 tick 放弃）
        p_cancel = 1 - math.exp(-config.P_CANCEL_PER_HOUR * (dt_min / 60.0))
        if world.rng.random() < p_cancel:
            t.status = "cancelled"
            t.cancelled_at = world.sim_now
            if r is not None and r.queue_waiting > 0:
                r.queue_waiting -= 1
            push_event(world, "queue.cancelled",
                       {"kind": "queue", "id": t.queue_code, "name": t.restaurant_name},
                       {"queue_code": t.queue_code, "restaurantId": t.restaurant_id},
                       f"❎ 排队号 {t.queue_code} 已自动放弃",
                       severity="info")
            continue

        # ahead 递减：餐厅翻台越快、越多空位放出，叫走越多
        prev_ahead = t.ahead
        serve_rate = config.QUEUE_SERVE_BASE_PER_MIN * (8.0 / max(1.0, turnover))
        served = _poisson(world, serve_rate * dt_min)
        # 若餐厅当前有空位，额外加速消化前排
        if r is not None and r.seats_free > 0:
            served += 1
        t.ahead = max(0, t.ahead - served)
        t.eta_min = round(t.ahead * turnover)

        subj = {"kind": "queue", "id": t.queue_code, "name": t.restaurant_name}

        # 阈值提醒（边沿一次性）：ahead 跨到 <= 阈值
        if (not t.threshold_hit and prev_ahead > config.QUEUE_THRESHOLD_AHEAD
                and t.ahead <= config.QUEUE_THRESHOLD_AHEAD and t.ahead > 0):
            t.threshold_hit = True
            push_event(world, "queue.threshold", subj,
                       {"queue_code": t.queue_code, "ahead": t.ahead,
                        "eta_min": t.eta_min, "restaurantId": t.restaurant_id},
                       f"⏳ 您的号 {t.queue_code} 前面只剩 {t.ahead} 桌，预计 {t.eta_min} 分钟",
                       severity="notice")

        # ahead 归 0 → 叫号
        if t.ahead == 0:
            t.status = "called"
            t.called_at = world.sim_now
            t.eta_min = 0
            push_event(world, "queue.called", subj,
                       {"queue_code": t.queue_code, "restaurantId": t.restaurant_id},
                       f"🔔 {t.queue_code} 已叫号，请尽快前往就座",
                       severity="alert")

    for code in to_delete:
        world.queue.pop(code, None)


# ════════════════════════ 天气演化 ════════════════════════

def evolve_weather(world: WorldState) -> None:
    """天气低频随机游走 + 马尔可夫转移；下雨跨边界触发 weather.changed + 联动。

    被 tick 调用，但仅当 (tick_count % WEATHER_TICK_EVERY == 0) 才真正动（慢变量）。
    若被 admin 锁定（weather_locked）则跳过自然演化。
    """
    if world.scripted_overrides.get("weather_locked"):
        return
    if world.tick_count % config.WEATHER_TICK_EVERY != 0:
        return

    w = world.weather
    prev_raining = w.is_raining
    prev_code = w.weather_code

    # 温度高斯游走（按 trend 给偏置），夹在合理区间
    drift = {"warming": 0.3, "cooling": -0.3}.get(w.trend, 0.0)
    w.temperature += world.rng.gauss(drift, config.TEMP_STEP_SIGMA)
    w.temperature = max(config.TEMP_MIN, min(config.TEMP_MAX, w.temperature))

    # 湿度 / 风速有界随机游走
    w.humidity = int(max(config.HUMIDITY_MIN, min(config.HUMIDITY_MAX,
                     w.humidity + world.rng.gauss(0, config.HUMIDITY_STEP_SIGMA))))
    w.wind_speed = max(config.WIND_MIN, min(config.WIND_MAX,
                     w.wind_speed + world.rng.gauss(0, config.WIND_STEP_SIGMA)))

    # weather_code 马尔可夫转移
    table = config.WEATHER_MARKOV.get(prev_code)
    if table:
        codes = [c for c, _ in table]
        weights = [p for _, p in table]
        w.weather_code = world.rng.choices(codes, weights=weights, k=1)[0]

    # 下雨时湿度抬升、体感降
    if w.weather_code in config.RAINY_CODES:
        w.humidity = max(w.humidity, world.rng.randint(70, 95))
    # 体感温度 = 温度 - f(风, 湿度)
    w.apparent_temperature = round(
        w.temperature - (w.wind_speed * 0.05) - (max(0, w.humidity - 60) * 0.02), 1)

    w.is_raining = w.weather_code in config.RAINY_CODES

    # trend 偶尔翻转，制造长期方向感
    if world.rng.random() < 0.15:
        w.trend = world.rng.choice(["warming", "cooling", "stable"])

    # 下雨跨边界 → 事件（开始下雨 / 雨停）
    if w.is_raining and not prev_raining:
        push_event(world, "weather.changed", {"kind": "weather", "area": "全城"},
                   {"weather_code": w.weather_code, "is_raining": True,
                    "temperature": round(w.temperature, 1)},
                   "🌧️ 开始下雨了，已为你联动调整出行与户外安排",
                   severity="notice")
    elif (not w.is_raining) and prev_raining:
        push_event(world, "weather.changed", {"kind": "weather", "area": "全城"},
                   {"weather_code": w.weather_code, "is_raining": False,
                    "temperature": round(w.temperature, 1)},
                   "🌤️ 雨停了，户外场所恢复推荐",
                   severity="notice")


# ════════════════════════ 娱乐场所演化 ════════════════════════

def evolve_venues(world: WorldState) -> None:
    """按 openHours 判定营业；健身团课名额随机消耗。雨天开闭由联动统一处理。"""
    dt_min = world.tick_minutes()
    for v in world.venues.values():
        # 被 admin 钉死关闭的场所跳过自然营业判定
        if v.id in world.scripted_overrides.get("closed_venues", set()):
            v.is_open_now = False
            continue

        # 户外场所的开闭交给 apply_weather_linkage 决定，这里只算"营业时间内"
        in_hours = _open_now(world, v.openHours)
        if v.is_outdoor:
            # 户外：营业时间内是否开放，最终由联动按是否下雨拍板；先记营业时间结果
            v.is_open_now = in_hours and not world.weather.is_raining
        else:
            v.is_open_now = in_hours

        # 健身团课名额随机消耗（动态可见量 spotsLeft）
        if v.classes:
            for c in v.classes:
                if c.get("spotsLeft", 0) > 0 and dt_min > 0:
                    if world.rng.random() < min(0.6, 0.04 * dt_min):
                        c["spotsLeft"] = max(0, c["spotsLeft"] - 1)


# ════════════════════════ 多类数据联动（E6） ════════════════════════

def apply_weather_linkage(world: WorldState) -> None:
    """下雨时统一施加联动；晴天恢复。一处实现，多处生效。

    - 餐厅排队↑：已在 evolve_restaurant 用 RAIN_DEMAND_MULT/RAIN_PFULL_BOOST 体现。
    - 室外娱乐：关闭 / 降权（is_open_now=False, weather_demoted, rating_effective-0.5）。
    - 打车：currentSurge=RAIN_SURGE（由 mobility router 读 weather.is_raining 体现）。
    - 出行 ETA：plan_route 内按 RAIN_ETA_MULT 放大。
    本函数核心负责"户外场所开闭/降权"的世界级状态改写 + 首次下雨的联动事件。
    """
    raining = world.weather.is_raining

    # 联动事件只在"刚下雨"那一刻 push 一次（边沿）：venue.closed + mobility.surge
    just_started = raining and not world.scripted_overrides.get("_linkage_active", False)
    just_stopped = (not raining) and world.scripted_overrides.get("_linkage_active", False)

    for v in world.venues.values():
        if not v.is_outdoor:
            v.weather_demoted = False
            v.weather_note = None
            v.rating_effective = v.rating
            continue
        # 户外场所
        if v.id in world.scripted_overrides.get("closed_venues", set()):
            continue
        if raining:
            was_open = v.is_open_now
            v.is_open_now = False
            v.weather_demoted = True
            v.weather_note = "雨天不建议户外"
            v.rating_effective = round(v.rating - 0.5, 1)
            if just_started and was_open:
                push_event(world, "venue.closed",
                           {"kind": "venue", "id": v.id, "name": v.name, "area": v.area},
                           {"reason": "rain", "venueId": v.id},
                           f"🌿 {v.name}因降雨暂不推荐，已为你降权",
                           severity="notice")
        else:
            # 晴天恢复：营业时间内则重新开放
            v.weather_demoted = False
            v.weather_note = None
            v.rating_effective = v.rating
            v.is_open_now = _open_now(world, v.openHours)

    # 打车加价事件（刚下雨时 push 一次）
    if just_started:
        push_event(world, "mobility.surge", {"kind": "mobility", "area": "全城"},
                   {"surge": config.RAIN_SURGE, "reason": "rain"},
                   f"🚕 雨天打车需求上升，当前加价约 {config.RAIN_SURGE}x",
                   severity="notice")
        world.scripted_overrides["_linkage_active"] = True
    if just_stopped:
        world.scripted_overrides["_linkage_active"] = False


# ════════════════════════ 控场算子（被 admin router 调用） ════════════════════════

def inject_scenario(world: WorldState, kind: str, params: dict) -> dict:
    """注入剧情（E7 演示控场）。返回 {success, kind, applied, event?, error?}。

    kind: rain | clear | restaurant_full | restaurant_seats |
          queue_threshold | queue_called | venue_closed | queue_surge
    调用方需持锁。
    """
    allowed = {"rain", "clear", "restaurant_full", "restaurant_seats",
               "queue_threshold", "queue_called", "venue_closed", "queue_surge"}
    if kind not in allowed:
        return {"success": False,
                "error": f"未知 kind: {kind}，允许: " + "|".join(sorted(allowed))}

    evt: WorldEvent | None = None
    applied: dict = {}

    if kind == "rain":
        w = world.weather
        w.weather_code = 61
        w.is_raining = True
        w.humidity = max(w.humidity, 88)
        w.apparent_temperature = round(w.temperature - 1.5, 1)
        world.scripted_overrides["weather_locked"] = True
        # 立刻施加联动（含 venue.closed / mobility.surge 边沿事件）
        evolve_venues(world)
        apply_weather_linkage(world)
        applied = {"weather_code": 61, "is_raining": True}
        evt = push_event(world, "weather.changed", {"kind": "weather", "area": "全城"},
                         {"weather_code": 61, "is_raining": True,
                          "temperature": round(w.temperature, 1)},
                         "🌧️ [控场] 立刻下雨，全套联动已触发",
                         severity="notice")

    elif kind == "clear":
        w = world.weather
        w.weather_code = 0
        w.is_raining = False
        world.scripted_overrides["weather_locked"] = True  # 锁定为晴，防止马上又变
        world.scripted_overrides["_linkage_active"] = False
        evolve_venues(world)
        apply_weather_linkage(world)
        applied = {"weather_code": 0, "is_raining": False}
        evt = push_event(world, "weather.changed", {"kind": "weather", "area": "全城"},
                         {"weather_code": 0, "is_raining": False,
                          "temperature": round(w.temperature, 1)},
                         "🌤️ [控场] 立刻转晴，户外恢复推荐",
                         severity="notice")

    elif kind == "restaurant_full":
        rid = params.get("restaurant_id")
        r = world.restaurants.get(rid)
        if r is None:
            return {"success": False, "error": f"找不到餐厅 {rid}"}
        r.queue_waiting += r.seats_free
        r.seats_free = 0
        r.is_full = True
        world.scripted_overrides.setdefault("locked_restaurants", set()).add(rid)
        applied = {"restaurant_id": rid, "seats_free": 0, "is_full": True}
        evt = push_event(world, "restaurant.full",
                         {"kind": "restaurant", "id": r.id, "name": r.name, "area": r.area},
                         {"restaurantId": r.id, "seats_free": 0, "area": r.area,
                          "queue_waiting": r.queue_waiting},
                         f"🍲 [控场] {r.name} 已被设为满座",
                         severity="alert")

    elif kind == "restaurant_seats":
        rid = params.get("restaurant_id")
        seats = int(params.get("seats") or 5)
        r = world.restaurants.get(rid)
        if r is None:
            return {"success": False, "error": f"找不到餐厅 {rid}"}
        r.seats_free = max(0, min(r.capacity, seats))
        r.is_full = r.seats_free == 0
        if r.seats_free > 0 and r.queue_waiting > 0:
            served = min(r.seats_free, r.queue_waiting)
            r.queue_waiting -= served  # 放位优先消化排队（更真实）
        applied = {"restaurant_id": rid, "seats_free": r.seats_free, "is_full": r.is_full}
        evt = push_event(world, "restaurant.has_seat",
                         {"kind": "restaurant", "id": r.id, "name": r.name, "area": r.area},
                         {"restaurantId": r.id, "seats_free": r.seats_free, "area": r.area},
                         f"🪑 [控场] {r.name} 立刻剩 {r.seats_free} 桌",
                         severity="notice")

    elif kind == "queue_surge":
        rid = params.get("restaurant_id")
        waiting = int(params.get("waiting") or 15)
        r = world.restaurants.get(rid)
        if r is None:
            return {"success": False, "error": f"找不到餐厅 {rid}"}
        r.queue_waiting = max(0, waiting)
        r.seats_free = 0
        r.is_full = True
        applied = {"restaurant_id": rid, "queue_waiting": r.queue_waiting}
        evt = push_event(world, "restaurant.queue_surge",
                         {"kind": "restaurant", "id": r.id, "name": r.name, "area": r.area},
                         {"restaurantId": r.id, "queue_waiting": r.queue_waiting, "area": r.area},
                         f"🔥 [控场] {r.name} 排队立刻涨到 {r.queue_waiting} 桌",
                         severity="notice")

    elif kind == "queue_threshold":
        code = params.get("queue_code")
        t = world.queue.get(code)
        if t is None:
            return {"success": False, "error": f"找不到排队号 {code}"}
        r = world.restaurants.get(t.restaurant_id)
        turnover = r.turnover_min_per_table if r else 8.0
        t.ahead = config.QUEUE_THRESHOLD_AHEAD
        t.eta_min = round(t.ahead * turnover)
        t.status = "waiting"
        t.threshold_hit = True
        applied = {"queue_code": code, "ahead": t.ahead, "eta_min": t.eta_min}
        evt = push_event(world, "queue.threshold",
                         {"kind": "queue", "id": code, "name": t.restaurant_name},
                         {"queue_code": code, "ahead": t.ahead,
                          "eta_min": t.eta_min, "restaurantId": t.restaurant_id},
                         f"⏳ [控场] {code} 前面只剩 {t.ahead} 桌",
                         severity="notice")

    elif kind == "queue_called":
        code = params.get("queue_code")
        t = world.queue.get(code)
        if t is None:
            return {"success": False, "error": f"找不到排队号 {code}"}
        t.status = "called"
        t.ahead = 0
        t.eta_min = 0
        t.called_at = world.sim_now
        applied = {"queue_code": code, "status": "called"}
        evt = push_event(world, "queue.called",
                         {"kind": "queue", "id": code, "name": t.restaurant_name},
                         {"queue_code": code, "restaurantId": t.restaurant_id},
                         f"🔔 [控场] {code} 立刻叫号，请就座",
                         severity="alert")

    elif kind == "venue_closed":
        vid = params.get("venue_id")
        v = world.venues.get(vid)
        if v is None:
            return {"success": False, "error": f"找不到场所 {vid}"}
        v.is_open_now = False
        v.weather_demoted = True
        world.scripted_overrides.setdefault("closed_venues", set()).add(vid)
        applied = {"venue_id": vid, "is_open_now": False}
        evt = push_event(world, "venue.closed",
                         {"kind": "venue", "id": v.id, "name": v.name, "area": v.area},
                         {"reason": "manual", "venueId": v.id},
                         f"🚧 [控场] {v.name} 已被设为关闭",
                         severity="notice")

    result = {"success": True, "kind": kind, "applied": applied, "sim_now": world.sim_iso()}
    if evt is not None:
        result["event"] = {"seq": evt.seq, "id": evt.id, "type": evt.type, "message": evt.message}
    return result


def set_clock(world: WorldState, time_scale: float | None,
              tick_seconds: float | None, paused: bool | None) -> dict:
    """改世界倍速 / tick 间隔 / 暂停（只改传入的非 None 字段）。调用方需持锁。"""
    if time_scale is not None:
        world.time_scale = max(0.1, float(time_scale))
    if tick_seconds is not None:
        world.tick_seconds = max(0.2, float(tick_seconds))
    if paused is not None:
        world.paused = bool(paused)

    real_per = world.tick_seconds
    world_min_per_tick = world.tick_seconds * world.time_scale / 60.0
    note = (f"世界已设为 {world.time_scale}x: 真实 {real_per:g}s "
            f"= 世界 {world_min_per_tick:.1f}min"
            + ("（已暂停）" if world.paused else ""))
    return {
        "success": True,
        "time_scale": world.time_scale,
        "tick_seconds": world.tick_seconds,
        "paused": world.paused,
        "note": note,
        "sim_now": world.sim_iso(),
    }


def reset_world(world: WorldState, seed: int | None, randomize: bool | None = None) -> None:
    """原地重建世界（保留同一 WorldState 对象引用，便于其他模块持有的引用不失效）。

    通过 build_world 造一个全新世界，再把字段逐一拷回当前单例。调用方需持锁。
    """
    from app.world.seed import build_world

    fresh = build_world(seed, randomize=randomize)
    # 逐字段覆盖（保留原 lock，避免正持锁的协程引用失效）
    world.rng = fresh.rng
    world.sim_now = fresh.sim_now
    world.time_scale = fresh.time_scale
    world.tick_seconds = fresh.tick_seconds
    world.tick_count = fresh.tick_count
    world.paused = fresh.paused
    world.restaurants = fresh.restaurants
    world.venues = fresh.venues
    world.areas = fresh.areas
    world.weather = fresh.weather
    world.queue = fresh.queue
    world.next_seq_per_rest = fresh.next_seq_per_rest
    world.events = fresh.events
    world.event_seq = fresh.event_seq
    world.scripted_overrides = fresh.scripted_overrides
