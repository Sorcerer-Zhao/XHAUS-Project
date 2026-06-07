# -*- coding: utf-8 -*-
"""FastAPI 应用入口（API 层）。

职责（SANDBOX_SPEC §8.3）：
  - 创建 FastAPI 实例。
  - lifespan：startup 用 asyncio.create_task 拉起后台世界时钟（E2），shutdown 优雅取消。
  - include 全部 7 个 router（restaurants / queue / weather / mobility /
    entertainment / events / admin）。
  - 加 CORS（全开，便于浏览器端 / skill 直接 fetch）。
  - 提供 GET /（健康检查 + 世界概览）与 GET /health（存活探针）。

并发约定：所有「读多字段拼响应」都在 `async with world.lock:` 内完成，
避免读到 tick 半途的撕裂状态。业务逻辑全在 world 单例的方法里，本层只做拼装。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.world.state import world
from app.world.clock import world_clock_loop
from app.routers import (
    restaurants,
    queue,
    weather,
    mobility,
    entertainment,
    events,
    admin,
)

logger = logging.getLogger("sandbox.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动后台时钟（E2），退出时干净取消。"""
    task = asyncio.create_task(world_clock_loop())
    logger.info("后台世界时钟已启动")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("后台世界时钟已停止")


app = FastAPI(
    title="全天候私人管家 · 动态沙盒",
    version="1.0",
    description="美团黑客松 · 任务④ 自建动态 Mock 后端 + 任务③ 7×24 主动协同事件流",
    lifespan=lifespan,
)

# CORS 全开，便于本地前端 / skill 直接 fetch
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册全部 router（模块名 + router 变量名 + prefix 均与 SPEC 契约一致）
for _m in (restaurants, queue, weather, mobility, entertainment, events, admin):
    app.include_router(_m.router)


@app.get("/", tags=["meta"])
async def root() -> dict:
    """健康检查 + 世界概览（对齐 API.md §1）。"""
    async with world.lock:
        return world.overview()


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """存活探针（对齐 API.md §2）。单字段只读，无需持锁。"""
    return {
        "status": "ok",
        "tick_count": world.tick_count,
        "sim_now": world.sim_iso(),
    }
