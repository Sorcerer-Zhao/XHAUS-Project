# -*- coding: utf-8 -*-
"""世界事件流 router（prefix /events）—— 任务③ 7×24 主动协同基座。

GET /events?since=<seq>&limit=&type=   增量事件（seq > since），幂等去重主键 = seq。
GET /events/stream?since=&type=        SSE 推送（可选，长连接持续吐新事件）。

管家心跳轮询 GET /events?since=lastSeq，据事件 type 主动发起动作（盯排队→剩N桌→提醒/叫车）。
读取逻辑全在 WorldState.read_events，本层只解析 query + 持锁调用。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.world.state import world

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def get_events(
    since: int = Query(default=0, description="只返回 seq > since 的事件（幂等去重主键）"),
    limit: int = Query(default=100, ge=1, description="最多返回条数，默认 100"),
    type: str | None = Query(  # noqa: A002  对齐 API 契约的 query 名
        default=None, description="按事件 type 过滤，逗号分隔多类型"
    ),
) -> dict:
    """增量事件流（对齐 API.md §13）。响应含 latest_seq，便于下次传 since。"""
    async with world.lock:
        return world.read_events(since=since, limit=limit, type_=type)


@router.get("/stream")
async def stream_events(
    since: int = Query(default=0, description="起始 seq，只推 seq > since 的事件"),
    type: str | None = Query(default=None, description="按 type 过滤，逗号分隔"),  # noqa: A002
):
    """SSE 长连接：持续推送新世界事件（每条一帧，data 为事件 JSON）。

    幂等：客户端断线重连时带上最后收到的 seq 作为 since 即可无缝续传。
    每帧 `id:` 为事件 seq，可配合浏览器 EventSource 的 lastEventId。
    """

    async def gen():
        last = since
        # 先把已有的历史增量一次性吐出
        while True:
            async with world.lock:
                resp = world.read_events(since=last, limit=200, type_=type)
            for e in resp["events"]:
                last = e["seq"]
                yield f"id: {e['seq']}\nevent: {e['type']}\n" \
                      f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            if not resp["events"]:
                # 没有新事件时发一个心跳注释，保持连接 + 让客户端知道还活着
                yield ": keep-alive\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
