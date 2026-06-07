# -*- coding: utf-8 -*-
"""排队 router（prefix /queue）。

POST /queue/take      取号
GET  /queue/status    查进度（query: queue_code）
POST /queue/cancel    取消

字段贴近现有 skill 的排队读法（queue_code/status/ahead/eta_min/status_text）。
排队的演化（ahead 递减 / 叫号 / 概率取消）由后台 tick 主动做，本层只读写一次状态。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models import QueueTakeRequest, QueueCancelRequest
from app.world.state import world

router = APIRouter(prefix="/queue", tags=["queue"])


@router.post("/take")
async def take(req: QueueTakeRequest) -> dict:
    """取号（对齐 API.md §5）。业务失败返回 200 + {success:false,error}。"""
    async with world.lock:
        return world.take_queue(
            restaurant_id=req.restaurant_id,
            people=req.people,
            customer_name=req.customer_name,
        )


@router.get("/status")
async def status(queue_code: str = Query(..., description="排队号，例 海07")) -> dict:
    """查排队进度（对齐 API.md §6）。"""
    async with world.lock:
        return world.queue_status(queue_code)


@router.post("/cancel")
async def cancel(req: QueueCancelRequest) -> dict:
    """取消排队（对齐 API.md §7）。非 waiting 不可取消。"""
    async with world.lock:
        return world.cancel_queue(req.queue_code)
