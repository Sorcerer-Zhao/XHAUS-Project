# -*- coding: utf-8 -*-
"""后台时钟（E2 核心）。

世界是"活"的关键：不是用户来查时才临时算随机数，而是这个 asyncio 后台循环
在真实时间里持续跑，每个 tick 主动推进世界一步。用户/skill 任何时刻去查，
都是在观测一个已经自己演化到某状态的世界。

被 main.lifespan 用 asyncio.create_task(world_clock_loop()) 拉起，应用退出时 task.cancel()。
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import timedelta

from app.world.state import world
from app.world import events as ev

logger = logging.getLogger("sandbox.clock")


async def tick() -> None:
    """推进世界一个步长。整个过程持锁，保证请求不会读到 tick 半途的撕裂状态。

    顺序（SANDBOX_SPEC §8.1）：
      1. 世界时钟前进 tick_seconds * time_scale 秒
      2. tick_count += 1
      3. 天气演化（低频，内部按 WEATHER_TICK_EVERY 判定是否真动）
      4. 逐餐厅演化（座位随机游走 / 概率翻满 / 排队消化 + 边沿事件）
      5. 排队票演化（ahead 递减 / 阈值提醒 / 叫号 / 概率取消）
      6. 天气联动统一施加（E6）
      7. 娱乐场所演化（营业时间 + 天气开闭）
    注：不在这里 sleep；sleep 由 loop 负责。
    """
    async with world.lock:
        # 1) 世界时钟前进
        world.sim_now += timedelta(seconds=world.tick_seconds * world.time_scale)
        # 2) 计数
        world.tick_count += 1
        # 3) 天气（低频）
        ev.evolve_weather(world)
        # 4) 餐厅
        for r in world.restaurants.values():
            ev.evolve_restaurant(world, r)
        # 5) 排队
        ev.evolve_queue(world)
        # 6) 联动（E6）
        ev.apply_weather_linkage(world)
        # 7) 娱乐
        ev.evolve_venues(world)


async def world_clock_loop() -> None:
    """后台主循环：未暂停则 await tick()，再 sleep(tick_seconds)。

    单 tick 异常被捕获并打日志后吞掉，保证循环不死（demo 现场不能因一次异常停摆）。
    sleep 时长动态读 world.tick_seconds，支持运行时改 tick 间隔。
    """
    logger.info("世界时钟启动：tick_seconds=%s, time_scale=%s",
                world.tick_seconds, world.time_scale)
    while True:
        try:
            if not world.paused:
                await tick()
        except asyncio.CancelledError:
            logger.info("世界时钟收到取消信号，退出")
            raise
        except Exception:  # noqa: BLE001  单 tick 异常不应杀死循环
            logger.error("tick 异常（已忽略，循环继续）：\n%s", traceback.format_exc())
        # sleep 放在锁外；时长实时读 world.tick_seconds
        await asyncio.sleep(max(0.2, world.tick_seconds))
