# -*- coding: utf-8 -*-
"""餐厅 router（prefix /restaurants）。

GET /restaurants        列表 / 筛选（area/cuisine/tag/budget/people/sort/limit，含 Top-N）
GET /restaurants/{id}   单餐厅详情

本层只做参数解析 + 持锁调用 world 方法；业务逻辑全在 WorldState.search_restaurants /
get_restaurant 里（见 world/state.py）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.world.state import world

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get("")
async def list_restaurants(
    area: str | None = Query(default=None, description="区域模糊匹配（area 或 address）"),
    cuisine: str | None = Query(default=None, description="菜系模糊匹配（cuisine 或 tags）"),
    tag: str | None = Query(default=None, description="标签模糊匹配"),
    budget: int | None = Query(default=None, description="人均×people ≤ budget；无结果软兜底略超 20%"),
    people: int = Query(default=1, ge=1, description="人数，默认 1"),
    sort: str = Query(default="rating", description="rating | price | wait"),
    limit: int = Query(default=5, ge=1, description="Top-N，默认 5"),
) -> dict:
    """餐厅列表 / 筛选（对齐 API.md §3）。"""
    async with world.lock:
        return world.search_restaurants(
            area=area,
            cuisine=cuisine,
            tag=tag,
            budget=budget,
            people=people,
            sort=sort,
            limit=limit,
        )


@router.get("/{rid}")
async def get_restaurant(rid: str) -> dict:
    """单餐厅详情（对齐 API.md §4）。找不到 → 404 {detail}。"""
    async with world.lock:
        r = world.get_restaurant(rid)
        if r is None:
            raise HTTPException(status_code=404, detail=f"找不到餐厅 {rid}")
        out = world.restaurant_to_public(r)
        out["capacity"] = r.capacity
        return out
