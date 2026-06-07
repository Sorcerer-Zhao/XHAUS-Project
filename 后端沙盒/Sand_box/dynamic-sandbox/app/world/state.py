# -*- coding: utf-8 -*-
"""世界内部状态 —— 全部用 @dataclass（不走 pydantic，频繁原地改字段）。

包含：
  - 各实体 dataclass：Restaurant / Venue / Area / Station / WeatherState / QueueTicket / WorldEvent
  - WorldState 总状态 dataclass（持有全部世界 + 一把 asyncio.Lock）
  - WorldState 上的查询/操作方法（搜餐厅、取号、查号、取消、查天气、算路线、搜娱乐、读事件流、
    快照、reset、inject、设时钟），供路由层直接调用——路由只做参数解析与响应拼装，业务都在这里。
  - 模块级全局单例 `world`（由 seed.build_world() 在导入末尾构造）。

并发约定（SANDBOX_SPEC §11）：
  - 改世界 / 读多字段拼响应：在 `async with world.lock:` 内完成。
  - 本文件方法多为"纯计算 + 原地改"，**不自己拿锁**；由调用方（路由 / clock.tick）统一持锁，
    避免可重入死锁。方法文档里标注是否需要调用方持锁。
  - 唯一时间源是 world.sim_now；本文件计算时间一律读它，绝不 datetime.now()（real_time 戳记除外）。
"""

from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app import config


# ════════════════════════ 实体 dataclass ════════════════════════

@dataclass
class Restaurant:
    """餐厅。对外可见字段贴合 mock-restaurants.json；隐藏状态驱动 waitInfo。"""
    # —— 对外可见 ——
    id: str
    name: str
    cuisine: str
    area: str
    address: str
    rating: float
    pricePerPerson: int
    tags: list[str]
    openHours: str
    phone: str
    highlights: list[str]
    shows: list[dict] | None = None
    # —— 隐藏演化状态（驱动 waitInfo / seatsFree / isFull）——
    capacity: int = 40                    # 总桌数
    seats_free: int = 10                  # 空桌数（0=已满），随机游走主变量
    queue_waiting: int = 0                # 当前排队桌数 = waitInfo.currentWait
    turnover_min_per_table: float = 8.0   # 每桌翻台耗时(分钟)，决定 avgWaitMinutes
    is_full: bool = False                 # seats_free==0
    base_popularity: float = 0.5          # 0~1 热门度，影响到店强度与涨满概率
    temporarily_closed: bool = False      # 临时打烊（重置时随机，与 openHours 无关）
    # —— 演化辅助：用于"翻台释放"的累积小数（避免每 tick 都被取整抹平）——
    _release_carry: float = 0.0

    # —— 派生（出口处计算）——
    @property
    def avg_wait_minutes(self) -> int:
        return round(self.queue_waiting * self.turnover_min_per_table)

    def to_public(self, sim_now: datetime, *, is_open: bool = True,
                  closed_reason: str | None = None) -> dict:
        """投影成对外 dict（camelCase，对齐现有 skill 读法）。"""
        out = {
            "id": self.id,
            "name": self.name,
            "cuisine": self.cuisine,
            "area": self.area,
            "address": self.address,
            "rating": self.rating,
            "pricePerPerson": self.pricePerPerson,
            "tags": list(self.tags),
            "openHours": self.openHours,
            "phone": self.phone,
            "waitInfo": {
                "currentWait": self.queue_waiting,
                "avgWaitMinutes": self.avg_wait_minutes,
            },
            "highlights": list(self.highlights),
            "shows": self.shows,
            "seatsFree": self.seats_free,
            "isFull": self.is_full,
            "isOpen": is_open,
        }
        if not is_open and closed_reason:
            out["closedReason"] = closed_reason
        return out


@dataclass
class Venue:
    """娱乐场所。字段名严格沿用 mock-entertainment.json。"""
    id: str
    type: str
    typeLabel: str
    name: str
    area: str
    address: str
    rating: float
    priceRange: str
    openHours: str
    tags: list[str]
    shows: list[dict] | None = None      # movie
    packages: list[dict] | None = None   # ktv
    themes: list[dict] | None = None     # escape_room / board_game
    classes: list[dict] | None = None    # fitness
    highlights: list[str] | None = None
    tonightEvent: dict | None = None     # bar
    # —— 隐藏演化状态 ——
    is_outdoor: bool = False             # 户外（park 等），雨天联动关闭/降权
    is_open_now: bool = True             # 受 openHours + 天气联动影响
    weather_demoted: bool = False        # 因天气被降权
    rating_effective: float = 0.0        # 联动后的有效评分（晴=rating，雨天户外 -0.5）
    weather_note: str | None = None      # 雨天提示文案

    def to_public(self) -> dict:
        """投影成对外 dict（含动态字段；themes 注入 themeName 别名）。"""
        # themes 补 themeName 别名（与 name 同值），让两种读法都成立
        themes = None
        if self.themes is not None:
            themes = []
            for t in self.themes:
                t2 = dict(t)
                if "name" in t2 and "themeName" not in t2:
                    t2["themeName"] = t2["name"]
                themes.append(t2)
        out = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "typeLabel": self.typeLabel,
            "area": self.area,
            "address": self.address,
            "rating": self.rating,
            "priceRange": self.priceRange,
            "openHours": self.openHours,
            "tags": list(self.tags),
            "shows": self.shows,
            "packages": self.packages,
            "themes": themes,
            "classes": self.classes,
            "highlights": self.highlights,
            "tonightEvent": self.tonightEvent,
            # 动态字段
            "isOpenNow": self.is_open_now,
            "isOutdoor": self.is_outdoor,
            "weatherDemoted": self.weather_demoted,
            "weatherNote": self.weather_note,
        }
        # 去掉为 None 的可选结构字段，保持输出干净（与 mock JSON 一致：没有就不出现）
        for k in ("shows", "packages", "themes", "classes", "highlights", "tonightEvent"):
            if out[k] is None:
                out.pop(k)
        return out


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

    def to_public(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "stations": [{"name": s.name, "lines": list(s.lines)} for s in self.stations],
        }


@dataclass
class WeatherState:
    """天气（仿 open-meteo current/daily）。"""
    temperature: float
    apparent_temperature: float
    humidity: int
    wind_speed: float
    weather_code: int
    is_raining: bool
    daily: list[dict]                # 长度3: [{date, max, min, code}]
    trend: str = "stable"            # warming | cooling | stable

    @staticmethod
    def code_is_rain(code: int) -> bool:
        return code in config.RAINY_CODES


@dataclass
class QueueTicket:
    """排队票。演化由后台 tick 主动做（ahead/eta 递减、概率叫号/取消）。"""
    queue_code: str
    restaurant_id: str
    restaurant_name: str
    address: str
    table_type: str
    table_type_label: str
    people: int
    customer_name: str
    status: str                      # waiting | called | seated | cancelled
    taken_at: datetime
    ahead: int
    eta_min: int
    initial_ahead: int = 0           # 取号时前面的桌数，用于"已服务 N 桌"进度
    threshold_hit: bool = False      # 是否已触发过 queue.threshold（边沿一次性）
    called_at: datetime | None = None
    seated_at: datetime | None = None
    cancelled_at: datetime | None = None


@dataclass
class WorldEvent:
    """世界事件（喂事件流，幂等去重靠 seq/id）。"""
    seq: int
    id: str
    type: str
    sim_time: str
    real_time: str
    subject: dict
    payload: dict
    message: str
    severity: str = "info"

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "sim_time": self.sim_time,
            "real_time": self.real_time,
            "subject": self.subject,
            "payload": self.payload,
            "message": self.message,
        }


# ════════════════════════ 世界总状态 ════════════════════════

@dataclass
class WorldState:
    """世界单例。持有全部状态 + 一把锁；并暴露给路由调用的查询/操作方法。"""
    lock: asyncio.Lock
    rng: random.Random
    sim_now: datetime
    time_scale: float
    tick_seconds: float
    tick_count: int
    paused: bool
    restaurants: dict[str, Restaurant]
    venues: dict[str, Venue]
    areas: dict[str, Area]
    weather: WeatherState
    queue: dict[str, QueueTicket]
    next_seq_per_rest: dict[str, int]
    events: list[WorldEvent]
    event_seq: int
    scripted_overrides: dict = field(default_factory=dict)

    # ───────────────────── 工具 ─────────────────────

    def tick_minutes(self) -> float:
        """本 tick 世界推进了多少分钟（= tick_seconds * time_scale / 60）。"""
        return self.tick_seconds * self.time_scale / 60.0

    def sim_iso(self) -> str:
        return self.sim_now.replace(microsecond=0).isoformat()

    def restaurant_open_info(self, r: Restaurant) -> tuple[bool, str | None]:
        """是否可接待（营业时间 + 非临时打烊 + 非控场关闭）。"""
        if r.id in self.scripted_overrides.get("closed_restaurants", set()):
            return False, "暂停营业"
        if r.temporarily_closed:
            return False, "临时休息"
        from app.world.events import _open_now
        if not _open_now(self, r.openHours):
            return False, "非营业时间"
        return True, None

    def restaurant_to_public(self, r: Restaurant) -> dict:
        is_open, reason = self.restaurant_open_info(r)
        out = r.to_public(self.sim_now, is_open=is_open, closed_reason=reason)
        out["sim_now"] = self.sim_iso()
        return out

    # ───────────────────── 餐厅查询 ─────────────────────

    def search_restaurants(
        self,
        area: str | None = None,
        cuisine: str | None = None,
        tag: str | None = None,
        budget: int | None = None,
        people: int = 1,
        sort: str = "rating",
        limit: int = 5,
    ) -> dict:
        """搜索/筛选餐厅。调用方需持锁（读多个实体拼响应）。

        返回与 API.md §3 对齐的 dict（query/count/total/hint/sim_now/restaurants）。
        """
        people = max(1, people)
        items = list(self.restaurants.values())

        def match(r: Restaurant) -> bool:
            if area and area not in r.area and area not in r.address:
                return False
            if cuisine and cuisine not in r.cuisine and not any(cuisine in t for t in r.tags):
                return False
            if tag and not any(tag in t for t in r.tags):
                return False
            return True

        matched = [r for r in items if match(r)]

        # 预算过滤：人均×people <= budget；无结果软兜底放宽 20%
        if budget is not None:
            strict = [r for r in matched if r.pricePerPerson * people <= budget]
            if strict:
                matched = strict
            else:
                soft = [r for r in matched if r.pricePerPerson * people <= budget * 1.2]
                matched = soft

        total = len(matched)

        # 排序：rating(默认 高→低) | price(人均 低→高) | wait(排队桌数 少→多)
        if sort == "price":
            matched.sort(key=lambda r: (r.pricePerPerson, -r.rating))
        elif sort == "wait":
            matched.sort(key=lambda r: (r.queue_waiting, -r.rating))
        else:  # rating
            matched.sort(key=lambda r: (-r.rating, r.queue_waiting))

        limit = max(1, limit)
        top = matched[:limit]

        if total == 0:
            hint = "没有找到符合条件的餐厅，换个区域或放宽预算试试～"
        elif total <= limit:
            hint = f"共 {total} 家符合条件"
        else:
            hint = f"共 {total} 家符合，已为你优选前 {len(top)} 家"

        query = {k: v for k, v in {
            "area": area, "cuisine": cuisine, "tag": tag,
            "budget": budget, "people": people, "sort": sort, "limit": limit,
        }.items() if v is not None}

        return {
            "query": query,
            "count": len(top),
            "total": total,
            "hint": hint,
            "sim_now": self.sim_iso(),
            "restaurants": [self.restaurant_to_public(r) for r in top],
        }

    def get_restaurant(self, rid: str) -> Restaurant | None:
        return self.restaurants.get(rid)

    # ───────────────────── 排队操作 ─────────────────────

    @staticmethod
    def _table_type_for(people: int) -> tuple[str, str]:
        for max_p, t, label in config.TABLE_TYPES:
            if people <= max_p:
                return t, label
        return config.TABLE_TYPES[-1][1], config.TABLE_TYPES[-1][2]

    def take_queue(self, restaurant_id: str, people: int, customer_name: str) -> dict:
        """取号。调用方需持锁。返回与 API.md §5 对齐的 dict。"""
        r = self.restaurants.get(restaurant_id)
        if r is None:
            return {"success": False, "error": f"找不到餐厅 {restaurant_id}"}

        is_open, reason = self.restaurant_open_info(r)
        if not is_open:
            return {"success": False, "error": f"「{r.name}」当前{reason or '未营业'}，暂不可取号"}

        people = max(1, people)
        table_type, table_label = self._table_type_for(people)

        # 生成排队号：餐厅名首字 + 两位递增序号
        seq = self.next_seq_per_rest.get(restaurant_id, 0) + 1
        self.next_seq_per_rest[restaurant_id] = seq
        first_char = r.name[0]
        queue_code = f"{first_char}{seq:02d}"

        # 前面桌数 = 当前排队桌数（若有空位则可能 0）。新票进队，餐厅排队 +1。
        ahead = r.queue_waiting if r.seats_free == 0 else 0
        r.queue_waiting += 1
        if r.seats_free == 0:
            r.is_full = True

        eta_min = round(ahead * r.turnover_min_per_table)
        ticket = QueueTicket(
            queue_code=queue_code,
            restaurant_id=restaurant_id,
            restaurant_name=r.name,
            address=r.address,
            table_type=table_type,
            table_type_label=table_label,
            people=people,
            customer_name=customer_name,
            status="waiting",
            taken_at=self.sim_now,
            ahead=ahead,
            eta_min=eta_min,
            initial_ahead=ahead,
        )
        # 取号即满足阈值则直接标记（避免下一 tick 才触发，体验更顺）
        if ahead <= config.QUEUE_THRESHOLD_AHEAD:
            ticket.threshold_hit = True
        self.queue[queue_code] = ticket

        est_call = self.sim_now + timedelta(minutes=eta_min)
        tips: list[str] = []
        if eta_min >= 20:
            tips.append("⏰ 等待较长，可以先去附近逛逛，快到号时我会提醒你")
        elif ahead == 0:
            tips.append("🎉 当前基本无需等位，可直接前往")
        else:
            tips.append("⏰ 等待不长，建议就近等候")
        if r.highlights:
            tips.append("🌟 推荐必点：" + "、".join(r.highlights[:2]))

        return {
            "success": True,
            "queue_code": queue_code,
            "restaurant_id": restaurant_id,
            "restaurant": r.name,
            "address": r.address,
            "table_type": table_type,
            "table_type_label": table_label,
            "people": people,
            "customer_name": customer_name,
            "ahead": ahead,
            "eta_min": eta_min,
            "status": "waiting",
            "taken_at": self.sim_iso(),
            "estimated_call_time": est_call.strftime("%H:%M"),
            "tips": tips,
        }

    def queue_status(self, queue_code: str) -> dict:
        """查排队进度。调用方需持锁。返回与 API.md §6 对齐的 dict。"""
        t = self.queue.get(queue_code)
        if t is None:
            return {"success": False, "error": f"找不到排队号 {queue_code}"}

        status_text = self._status_text(t)
        served = max(0, t.initial_ahead - t.ahead)
        out = {
            "success": True,
            "queue_code": t.queue_code,
            "restaurant": t.restaurant_name,
            "address": t.address,
            "table_type": t.table_type_label,
            "people": t.people,
            "status": t.status,
            "ahead": t.ahead,
            "eta_min": t.eta_min,
            "status_text": status_text,
            "sim_now": self.sim_iso(),
        }
        if t.status == "waiting":
            est_call = self.sim_now + timedelta(minutes=t.eta_min)
            out["estimated_call_time"] = est_call.strftime("%H:%M")
            out["progress"] = f"已服务 {served} 桌"
        return out

    @staticmethod
    def _status_text(t: QueueTicket) -> str:
        if t.status == "called":
            return "🔔 已叫号！请尽快前往餐厅就座"
        if t.status == "seated":
            return "已入座"
        if t.status == "cancelled":
            return "已取消"
        # waiting
        if t.ahead <= 0:
            return "马上到号，请就位"
        return f"排队中，前面还有 {t.ahead} 桌"

    def cancel_queue(self, queue_code: str) -> dict:
        """取消排队。调用方需持锁。"""
        t = self.queue.get(queue_code)
        if t is None:
            return {"success": False, "error": f"找不到排队号 {queue_code}"}
        if t.status != "waiting":
            label = {"called": "已叫号", "seated": "已入座", "cancelled": "已取消"}.get(t.status, t.status)
            return {"success": False, "error": f"排队号 {queue_code} 当前状态「{label}」，无法取消"}
        t.status = "cancelled"
        t.cancelled_at = self.sim_now
        # 该票退出排队，餐厅排队 -1
        r = self.restaurants.get(t.restaurant_id)
        if r is not None and r.queue_waiting > 0:
            r.queue_waiting -= 1
        return {
            "success": True,
            "queue_code": queue_code,
            "status": "cancelled",
            "message": f"排队号 {queue_code} 已取消",
        }

    # ───────────────────── 天气查询 ─────────────────────

    def weather_payload(self, area: str | None = None) -> dict:
        """组装仿 open-meteo 响应。调用方需持锁。"""
        resolved = area if (area and area in self.areas) else "望京"
        a = self.areas.get(resolved)
        lat = a.lat if a else 39.997
        lon = a.lon if a else 116.474
        w = self.weather
        current_time = self.sim_now.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        daily = w.daily
        return {
            "latitude": lat,
            "longitude": lon,
            "timezone": "Asia/Shanghai",
            "area": resolved,
            "sim_now": self.sim_iso(),
            "current": {
                "time": current_time,
                "temperature_2m": round(w.temperature, 1),
                "apparent_temperature": round(w.apparent_temperature, 1),
                "relative_humidity_2m": int(w.humidity),
                "wind_speed_10m": round(w.wind_speed, 1),
                "weather_code": w.weather_code,
            },
            "daily": {
                "time": [d["date"] for d in daily],
                "temperature_2m_max": [d["max"] for d in daily],
                "temperature_2m_min": [d["min"] for d in daily],
                "weather_code": [d["code"] for d in daily],
            },
            "is_raining": w.is_raining,
        }

    # ───────────────────── 出行 ─────────────────────

    def mobility_config(self) -> dict:
        """GET /mobility/areas —— 区域 + 出行配置。调用方需持锁（taxiConfig.currentSurge 动态）。"""
        taxi = dict(config.TAXI_CONFIG)
        taxi["avgSpeedKmH"] = dict(config.TAXI_CONFIG["avgSpeedKmH"])
        taxi["currentSurge"] = config.RAIN_SURGE if self.weather.is_raining else config.CLEAR_SURGE
        return {
            "areas": {name: a.to_public() for name, a in self.areas.items()},
            "subwayConfig": config.SUBWAY_CONFIG,
            "taxiConfig": taxi,
            "walkConfig": config.WALK_CONFIG,
        }

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """两点球面距离（km）。"""
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(h))

    @staticmethod
    def _in_window(hhmm: str, windows: list[str]) -> bool:
        """判定 HH:MM 是否落在任一 'HH:MM-HH:MM' 窗口内（含跨午夜）。"""
        def to_min(s: str) -> int:
            h, m = s.split(":")
            return int(h) * 60 + int(m)
        cur = to_min(hhmm)
        for w in windows:
            a, b = w.split("-")
            am, bm = to_min(a), to_min(b)
            if am <= bm:
                if am <= cur <= bm:
                    return True
            else:  # 跨午夜
                if cur >= am or cur <= bm:
                    return True
        return False

    def plan_route(self, frm: str, to: str, time_str: str | None = None, mode: str = "all") -> dict:
        """出行方案对比（含雨天联动）。调用方需持锁。对齐 API.md §10。"""
        if frm not in self.areas:
            return {"success": False, "error": f"无法识别出发地「{frm}」",
                    "hint": "支持的区域：" + "、".join(config.AREAS)}
        if to not in self.areas:
            return {"success": False, "error": f"无法识别目的地「{to}」",
                    "hint": "支持的区域：" + "、".join(config.AREAS)}

        a, b = self.areas[frm], self.areas[to]
        dist = self._haversine_km(a.lat, a.lon, b.lat, b.lon)
        dist = max(0.5, dist)  # 同点也给个最小距离避免 0

        # 出发时刻：默认用 sim_now
        if time_str:
            dep_hhmm = time_str
            try:
                hh, mm = [int(x) for x in time_str.split(":")]
                dep = self.sim_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            except Exception:
                dep = self.sim_now
                dep_hhmm = self.sim_now.strftime("%H:%M")
        else:
            dep = self.sim_now
            dep_hhmm = self.sim_now.strftime("%H:%M")

        raining = self.weather.is_raining
        taxi_cfg = config.TAXI_CONFIG
        sub_cfg = config.SUBWAY_CONFIG
        walk_cfg = config.WALK_CONFIG

        is_peak = self._in_window(dep_hhmm, taxi_cfg["peakHours"])
        is_night = self._in_window(dep_hhmm, taxi_cfg["nightHours"])

        plans: list[dict] = []
        want = lambda m: mode in ("all", m)

        # —— 地铁 ——
        if want("subway"):
            sub_speed = sub_cfg["avgSpeedKmH"]
            ride_min = dist / sub_speed * 60
            transfers = 0 if dist < 5 else (1 if dist < 14 else 2)
            sub_min = round(ride_min + transfers * sub_cfg["transferMinutes"]
                            + sub_cfg["walkToStationMinutes"])
            if raining:
                sub_min = round(sub_min * 1.05)  # 雨天地铁影响小
            # 票价：按距离阈值
            price = sub_cfg["priceRules"]["base"]
            for th in sub_cfg["priceRules"]["thresholds"]:
                if dist <= th["km"]:
                    price = th["price"]
                    break
            else:
                price = sub_cfg["priceRules"]["thresholds"][-1]["price"]
            from_st = a.stations[0]
            to_st = b.stations[0]
            if transfers > 0:
                route = (f"{from_st.name}（{from_st.lines[0]}）→ 换乘 → "
                         f"{to_st.name}（{to_st.lines[0]}）")
            else:
                route = f"{from_st.name}（{from_st.lines[0]}）→ {to_st.name}"
            arr = (dep + timedelta(minutes=sub_min)).strftime("%H:%M")
            cons = ["步行到站约 6 分钟"]
            if transfers > 0:
                cons.insert(0, "需要换乘")
            plans.append({
                "mode": "🚇 地铁",
                "duration": f"约 {sub_min} 分钟",
                "durationMinutes": sub_min,
                "cost": f"¥{price}",
                "costValue": price,
                "route": route,
                "transfers": transfers,
                "arrivalTime": arr,
                "pros": ["准时可控，不受堵车影响", "费用最低"],
                "cons": cons,
            })

        # —— 打车 ——
        if want("taxi"):
            speed = taxi_cfg["avgSpeedKmH"]["peak"] if is_peak else taxi_cfg["avgSpeedKmH"]["normal"]
            base_min = dist / speed * 60
            surge = config.RAIN_SURGE if raining else config.CLEAR_SURGE
            taxi_min = base_min
            if raining:
                taxi_min *= config.RAIN_ETA_MULT
            taxi_min = round(taxi_min)
            # 费用：起步 + 超出里程
            fare = taxi_cfg["baseFare"] + max(0.0, dist - taxi_cfg["baseKm"]) * taxi_cfg["perKm"]
            if is_peak:
                fare *= taxi_cfg["peakMultiplier"]
            if is_night:
                fare *= taxi_cfg["nightMultiplier"]
            fare *= surge
            cost_lo = round(fare * 0.9)
            cost_hi = round(fare * 1.2)
            cost_val = round(fare)
            arr = (dep + timedelta(minutes=taxi_min)).strftime("%H:%M")
            pros = ["门到门，最省力"]
            cons: list[str] = []
            plan = {
                "mode": "🚕 打车",
                "duration": f"约 {round(taxi_min*0.9)}-{round(taxi_min*1.15)} 分钟",
                "durationMinutes": taxi_min,
                "cost": f"¥{cost_lo}-{cost_hi}",
                "costValue": cost_val,
                "distance": f"{dist:.1f} km",
                "arrivalTime": arr,
                "surge": surge,
                "pros": pros,
                "cons": cons,
            }
            if is_peak:
                plan["peakWarning"] = True
                cons.append("⚠️ 高峰时段易堵")
            if raining:
                plan["peakWarning"] = True
                plan["weatherNote"] = f"雨天打车需求大、加价约 {surge}x"
                cons.append("⚠️ 雨天易堵")
                cons.append(f"当前加价 {surge}x")
            if not cons:
                cons.append("受路况影响有不确定性")
            plans.append(plan)

        # —— 步行 ——
        if want("walk") and dist <= walk_cfg["maxRecommendKm"] + 1.5:
            walk_min = round(dist / walk_cfg["speedKmH"] * 60)
            arr = (dep + timedelta(minutes=walk_min)).strftime("%H:%M")
            cons = []
            if dist > walk_cfg["maxRecommendKm"]:
                cons.append("距离略远，步行较累")
            if raining:
                cons.append("☔ 雨天不建议步行")
            if not cons:
                cons.append("纯步行，注意天气")
            plans.append({
                "mode": "🚶 步行",
                "duration": f"约 {walk_min} 分钟",
                "durationMinutes": walk_min,
                "cost": "¥0",
                "costValue": 0,
                "distance": f"{dist:.1f} km",
                "arrivalTime": arr,
                "pros": ["免费", "顺便散步"],
                "cons": cons,
            })

        # —— 推荐：雨天优先地铁，否则按时长 ——
        if plans:
            if raining:
                rec = min(plans, key=lambda p: (0 if "地铁" in p["mode"] else 1, p["durationMinutes"]))
            else:
                rec = min(plans, key=lambda p: p["durationMinutes"])
            recommended = rec["mode"]
        else:
            recommended = ""

        out = {
            "success": True,
            "from": frm,
            "to": to,
            "distance": f"{dist:.1f} km",
            "departureTime": dep_hhmm,
            "recommended": recommended,
            "plans": plans,
        }
        if raining:
            out["weatherNote"] = "雨天打车加价并易堵，地铁更稳"
        return out

    # ───────────────────── 娱乐查询 ─────────────────────

    def search_venues(
        self,
        area: str | None = None,
        type_: str | None = None,
        time_str: str | None = None,
        people: int | None = None,
        budget: int | None = None,
        mood: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """搜索/筛选娱乐场所（含雨天降权）。调用方需持锁。对齐 API.md §11。"""
        items = list(self.venues.values())

        def match(v: Venue) -> bool:
            if area and area not in v.area and area not in v.address:
                return False
            if type_ and type_ != "all" and v.type != type_:
                return False
            if mood:
                mood_map = {
                    "quiet": {"bar", "spa", "massage", "park"},
                    "lively": {"bar", "ktv", "billiards"},
                    "active": {"fitness", "escape_room", "billiards"},
                    "relaxed": {"spa", "massage", "park", "shopping", "movie"},
                }
                allow = mood_map.get(mood)
                if allow and v.type not in allow:
                    return False
            return True

        matched = [v for v in items if match(v)]

        # 排序：营业中优先 → 未被天气降权优先 → 有效评分高优先
        def rank_key(v: Venue):
            eff = v.rating_effective if v.rating_effective else v.rating
            return (0 if v.is_open_now else 1, 1 if v.weather_demoted else 0, -eff)

        matched.sort(key=rank_key)

        if limit:
            matched = matched[: max(1, limit)]

        weather_note = None
        if self.weather.is_raining and any(v.weather_demoted for v in items):
            weather_note = "正在下雨，已为你降低了户外场所的优先级"

        query = {k: v for k, v in {
            "area": area, "type": type_ or "all", "time": time_str,
            "people": people, "budget": budget, "mood": mood, "limit": limit,
        }.items() if v is not None}

        return {
            "query": query,
            "count": len(matched),
            "sim_now": self.sim_iso(),
            "weatherNote": weather_note,
            "venues": [v.to_public() for v in matched],
        }

    def get_venue(self, vid: str) -> Venue | None:
        return self.venues.get(vid)

    # ───────────────────── 事件流 ─────────────────────

    def read_events(self, since: int = 0, limit: int = 100, type_: str | None = None) -> dict:
        """读取 seq > since 的事件（可按 type 逗号分隔过滤）。调用方需持锁。"""
        types = None
        if type_:
            types = {t.strip() for t in type_.split(",") if t.strip()}
        out: list[dict] = []
        for e in self.events:
            if e.seq <= since:
                continue
            if types and e.type not in types:
                continue
            out.append(e.to_dict())
        latest = self.events[-1].seq if self.events else self.event_seq
        limit = max(1, limit)
        out = out[:limit]
        return {
            "since": since,
            "latest_seq": latest,
            "count": len(out),
            "sim_now": self.sim_iso(),
            "events": out,
        }

    # ───────────────────── 快照 ─────────────────────

    def overview(self) -> dict:
        """GET / —— 世界概览。调用方需持锁。"""
        active = [t for t in self.queue.values() if t.status in ("waiting", "called")]
        return {
            "service": "全天候私人管家 · 动态沙盒",
            "version": "1.0",
            "sim_now": self.sim_iso(),
            "time_scale": self.time_scale,
            "tick_seconds": self.tick_seconds,
            "tick_count": self.tick_count,
            "paused": self.paused,
            "counts": {
                "restaurants": len(self.restaurants),
                "venues": len(self.venues),
                "areas": len(self.areas),
                "active_queue": len(active),
            },
            "weather": {
                "weather_code": self.weather.weather_code,
                "is_raining": self.weather.is_raining,
                "temperature": round(self.weather.temperature, 1),
            },
            "latest_event_seq": self.event_seq,
        }

    def snapshot(self) -> dict:
        """GET /admin/state —— 全局快照（debug）。调用方需持锁。"""
        return {
            "sim_now": self.sim_iso(),
            "time_scale": self.time_scale,
            "tick_count": self.tick_count,
            "paused": self.paused,
            "weather": {
                "weather_code": self.weather.weather_code,
                "is_raining": self.weather.is_raining,
                "temperature": round(self.weather.temperature, 1),
                "trend": self.weather.trend,
            },
            "restaurants": [
                {"id": r.id, "name": r.name, "seats_free": r.seats_free,
                 "queue_waiting": r.queue_waiting, "is_full": r.is_full}
                for r in self.restaurants.values()
            ],
            "venues_closed": [v.id for v in self.venues.values() if not v.is_open_now],
            "active_queue": [
                {"queue_code": t.queue_code, "status": t.status,
                 "ahead": t.ahead, "eta_min": t.eta_min}
                for t in self.queue.values() if t.status in ("waiting", "called")
            ],
            "event_seq": self.event_seq,
            "scripted_overrides": self.scripted_overrides,
        }


# ════════════════════════ 全局单例 ════════════════════════
# 由 seed.build_world() 构造。放在文件末尾导入以避免循环依赖。
from app.world.seed import build_world  # noqa: E402

world: WorldState = build_world()
