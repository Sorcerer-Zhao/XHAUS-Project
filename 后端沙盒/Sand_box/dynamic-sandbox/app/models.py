# -*- coding: utf-8 -*-
"""API 出入参的 pydantic v2 模型。

契约要点（见 SANDBOX_SPEC §4 / §11）：
  - pydantic 仅用于 **API 层** 的入参校验 + 出参序列化。
  - 世界内部状态用 dataclass（见 world/state.py），频繁原地改字段、不走 pydantic 校验。
  - 出口字段名严格对齐现有 skill 读法（camelCase：waitInfo / pricePerPerson / typeLabel …），
    保证 skill 把 loadData() 换成 HTTP fetch 后零改造。

这里的"出参模型"主要给路由层做 response_model / 文档示例用；
路由实际返回时也可直接吐 dict（FastAPI 都接受）。入参模型（请求体）则是硬校验。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ════════════════════════ 通用 / 健康检查 ════════════════════════

class WeatherBrief(BaseModel):
    """根路由概览里的天气简报。"""
    weather_code: int
    is_raining: bool
    temperature: float


class RootResponse(BaseModel):
    """GET / —— 健康检查 + 世界概览。"""
    service: str
    version: str
    sim_now: str
    time_scale: float
    tick_seconds: float
    tick_count: int
    paused: bool
    counts: dict[str, int]
    weather: WeatherBrief
    latest_event_seq: int


class HealthResponse(BaseModel):
    """GET /health —— 存活探针。"""
    status: str = "ok"
    tick_count: int
    sim_now: str


# ════════════════════════ 餐厅 ════════════════════════

class WaitInfo(BaseModel):
    """派生的等位信息（对齐 mock-restaurants.json）。"""
    currentWait: int       # 当前排队桌数
    avgWaitMinutes: int    # 预计等待分钟


class RestaurantOut(BaseModel):
    """单餐厅对外投影（字段对齐 mock-restaurants.json + 新增动态字段）。"""
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
    waitInfo: WaitInfo
    highlights: list[str]
    shows: list[dict] | None = None
    # —— 本沙盒新增动态字段（旧 skill 忽略即可） ——
    seatsFree: int
    isFull: bool


class RestaurantListResponse(BaseModel):
    """GET /restaurants —— 列表/筛选。"""
    query: dict[str, Any]
    count: int
    total: int
    hint: str
    sim_now: str
    restaurants: list[RestaurantOut]


# ════════════════════════ 排队 ════════════════════════

class QueueTakeRequest(BaseModel):
    """POST /queue/take 请求体。"""
    restaurant_id: str
    people: int = Field(default=1, ge=1, le=50)
    customer_name: str = "顾客"


class QueueCancelRequest(BaseModel):
    """POST /queue/cancel 请求体。"""
    queue_code: str


# 排队出参字段较灵活（不同 status 字段略异），路由层直接吐 dict，
# 这里只声明请求体的硬校验模型。


# ════════════════════════ 娱乐 ════════════════════════

class VenueOut(BaseModel):
    """单娱乐场所对外投影（字段对齐 mock-entertainment.json + 动态字段）。

    可选结构字段按 type 出现：shows/packages/themes/classes/tonightEvent。
    主题对象同时带 name 与 themeName（别名），两种读法都成立。
    """
    id: str
    name: str
    type: str
    typeLabel: str
    area: str
    address: str
    rating: float
    priceRange: str
    openHours: str
    tags: list[str]
    shows: list[dict] | None = None
    packages: list[dict] | None = None
    themes: list[dict] | None = None
    classes: list[dict] | None = None
    highlights: list[str] | None = None
    tonightEvent: dict | None = None
    # —— 动态字段 ——
    isOpenNow: bool
    isOutdoor: bool | None = None
    weatherDemoted: bool | None = None
    weatherNote: str | None = None


class VenueListResponse(BaseModel):
    """GET /entertainment —— 列表/筛选。"""
    query: dict[str, Any]
    count: int
    sim_now: str
    weatherNote: str | None = None
    venues: list[VenueOut]


# ════════════════════════ 天气（仿 open-meteo） ════════════════════════

class WeatherCurrent(BaseModel):
    time: str
    temperature_2m: float
    apparent_temperature: float
    relative_humidity_2m: int
    wind_speed_10m: float
    weather_code: int


class WeatherDaily(BaseModel):
    time: list[str]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    weather_code: list[int]


class WeatherResponse(BaseModel):
    """GET /weather —— 严格仿 open-meteo Forecast。"""
    latitude: float
    longitude: float
    timezone: str = "Asia/Shanghai"
    area: str
    sim_now: str
    current: WeatherCurrent
    daily: WeatherDaily
    is_raining: bool


# ════════════════════════ 世界事件流 ════════════════════════

class WorldEventOut(BaseModel):
    """单条世界事件（对齐 WorldEvent dataclass 出口）。"""
    seq: int
    id: str
    type: str
    severity: str
    sim_time: str
    real_time: str
    subject: dict
    payload: dict
    message: str


class EventsResponse(BaseModel):
    """GET /events —— 增量事件流。"""
    since: int
    latest_seq: int
    count: int
    sim_now: str
    events: list[WorldEventOut]


# ════════════════════════ 控场（admin） ════════════════════════

class InjectRequest(BaseModel):
    """POST /admin/inject —— 注入剧情。

    kind 决定剧情，额外字段按 kind 取用（见 API.md §14）：
      rain | clear | restaurant_full | restaurant_seats |
      queue_surge | queue_threshold | queue_called | venue_closed
    """
    kind: str
    restaurant_id: str | None = None
    venue_id: str | None = None
    queue_code: str | None = None
    seats: int | None = None
    waiting: int | None = None


class ClockRequest(BaseModel):
    """POST /admin/clock —— 改世界倍速 / 暂停（字段均可选，只改传入的）。"""
    time_scale: float | None = None
    tick_seconds: float | None = None
    paused: bool | None = None


class ResetRequest(BaseModel):
    """POST /admin/reset —— 重置世界（可选 seed 复现同一随机世界）。"""
    seed: int | None = None
    randomize: bool | None = None  # 默认 true：随机初始排队/空桌/打烊
