# -*- coding: utf-8 -*-
"""娱乐 router（prefix /entertainment）。

GET /entertainment        列表 / 筛选（area/type/time/people/budget/mood/limit）
GET /entertainment/{id}   单场所详情

雨天对户外场所的关闭 / 降权由后台 tick + 联动主动做（E6），本层只读出当前状态。
主题对象的 themeName 别名在 Venue.to_public() 里注入。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.world.state import world

router = APIRouter(prefix="/entertainment", tags=["entertainment"])


@router.get("")
async def list_venues(
    area: str | None = Query(default=None, description="区域模糊匹配"),
    type: str | None = Query(  # noqa: A002  对齐 API 契约的 query 名
        default=None,
        description="movie|bar|ktv|escape_room|board_game|park|fitness|spa|massage|billiards|shopping|all",
    ),
    time: str | None = Query(default=None, description="时刻 HH:MM"),
    people: int | None = Query(default=None, description="人数"),
    budget: int | None = Query(default=None, description="预算"),
    mood: str | None = Query(default=None, description="quiet|lively|active|relaxed"),
    limit: int | None = Query(default=None, description="Top-N"),
) -> dict:
    """娱乐列表 / 筛选（对齐 API.md §11，含雨天降权 weatherNote）。"""
    async with world.lock:
        return world.search_venues(
            area=area,
            type_=type,
            time_str=time,
            people=people,
            budget=budget,
            mood=mood,
            limit=limit,
        )


@router.get("/{vid}")
async def get_venue(vid: str) -> dict:
    """单娱乐场所详情（对齐 API.md §12）。找不到 → 404 {detail}。"""
    async with world.lock:
        v = world.get_venue(vid)
        if v is None:
            raise HTTPException(status_code=404, detail=f"找不到场所 {vid}")
        out = v.to_public()
        out["sim_now"] = world.sim_iso()
        return out
