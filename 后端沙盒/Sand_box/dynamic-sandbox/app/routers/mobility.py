# -*- coding: utf-8 -*-
"""出行 router（prefix /mobility）。

GET /mobility/areas   区域坐标 + 出行配置（subway/taxi/walk；taxiConfig.currentSurge 动态）
GET /mobility/plan    出行方案对比（含雨天 surge / ETA 联动，E6）

`from` 是 Python 保留字，用 Query(alias="from") 映射；同时兼容 `to`。
出行算法（haversine / 高峰 / 雨天联动）全在 WorldState.plan_route，本层只透传参数。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.world.state import world

router = APIRouter(prefix="/mobility", tags=["mobility"])


@router.get("/areas")
async def areas() -> dict:
    """区域 + 出行配置（对齐 API.md §9）。taxiConfig.currentSurge 随天气动态。"""
    async with world.lock:
        return world.mobility_config()


@router.get("/plan")
async def plan(
    frm: str = Query(..., alias="from", description="出发地（区域名）"),
    to: str = Query(..., description="目的地（区域名）"),
    time: str | None = Query(default=None, description="出发时刻 HH:MM，默认用 sim_now"),
    mode: str = Query(default="all", description="all | subway | taxi | walk | bike"),
) -> dict:
    """出行方案对比（对齐 API.md §10）。识别不到区域返回 200 + {success:false,error,hint}。"""
    async with world.lock:
        return world.plan_route(frm=frm, to=to, time_str=time, mode=mode)
