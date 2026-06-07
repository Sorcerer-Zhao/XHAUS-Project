# -*- coding: utf-8 -*-
"""控场 router（prefix /admin）—— E7 演示控场。

POST /admin/inject   注入剧情（让某餐厅立刻满座/剩N桌/立刻下雨等）
POST /admin/clock    改世界倍速 / tick 间隔 / 暂停（加速让 10min 演化在数十秒看完）
POST /admin/reset    重置世界（可选 seed 复现同一随机世界）
GET  /admin/state    世界全局快照（debug）

控场算子全在 app.world.events（inject_scenario / set_clock / reset_world），本层只持锁转调。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models import InjectRequest, ClockRequest, ResetRequest
from app.world.state import world
from app.world import events as ev

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/inject")
async def inject(req: InjectRequest) -> dict:
    """注入剧情（对齐 API.md §14）。未知 kind / 找不到资源 → 200 + {success:false,error}。"""
    # 把请求体里 kind 之外的字段收成 params 传给算子（None 也无妨，算子内有默认值）
    params = {
        "restaurant_id": req.restaurant_id,
        "venue_id": req.venue_id,
        "queue_code": req.queue_code,
        "seats": req.seats,
        "waiting": req.waiting,
    }
    async with world.lock:
        return ev.inject_scenario(world, req.kind, params)


@router.post("/clock")
async def clock(req: ClockRequest) -> dict:
    """改世界倍速 / 暂停（对齐 API.md §15）。只改传入的非 None 字段。"""
    async with world.lock:
        return ev.set_clock(
            world,
            time_scale=req.time_scale,
            tick_seconds=req.tick_seconds,
            paused=req.paused,
        )


@router.post("/reset")
async def reset(req: ResetRequest | None = None) -> dict:
    """重置世界（对齐 API.md §16）。传 seed 可复现同一随机世界。"""
    seed = req.seed if req is not None else None
    randomize = req.randomize if req is not None else None
    async with world.lock:
        ev.reset_world(world, seed, randomize=randomize)
        return {
            "success": True,
            "message": "世界已重置",
            "seed": seed,
            "randomize": randomize,
            "sim_now": world.sim_iso(),
            "counts": {
                "restaurants": len(world.restaurants),
                "venues": len(world.venues),
                "areas": len(world.areas),
            },
        }


def _jsonable(obj):
    """把快照里可能出现的 set（scripted_overrides 的 locked_restaurants 等）
    递归转成 list，保证 FastAPI 能序列化（核心层 snapshot 会原样返回 set）。"""
    if isinstance(obj, set):
        return sorted(obj, key=str)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


@router.get("/state")
async def state() -> dict:
    """世界全局快照（对齐 API.md §17）。"""
    async with world.lock:
        return _jsonable(world.snapshot())
