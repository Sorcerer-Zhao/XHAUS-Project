# -*- coding: utf-8 -*-
"""天气 router（prefix /weather）。

GET /weather?area=   仿 open-meteo 的天气（全城统一一份；传 area 也返回同一份）。

天气由后台 tick（低频 + 联动 / admin inject）演化，本层只读出当前快照。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.world.state import world

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("")
async def get_weather(
    area: str | None = Query(default=None, description="区域（默认全城统一一份天气）"),
    lat: float | None = Query(default=None, description="占位，返回同一份"),
    lon: float | None = Query(default=None, description="占位，返回同一份"),
) -> dict:
    """天气（对齐 API.md §8，严格仿 open-meteo current/daily）。"""
    async with world.lock:
        return world.weather_payload(area=area)
