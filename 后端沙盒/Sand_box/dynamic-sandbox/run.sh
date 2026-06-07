#!/usr/bin/env bash
# 动态模拟沙盒后端 · 一行启动脚本
#
# 重要: 本沙盒是"有状态单进程"——后台 asyncio 时钟在进程内存里驱动整个世界。
# 因此必须单 worker、禁用 --reload。
#   --reload 会用子进程热重载，频繁杀死/重建进程，导致后台时钟所在子进程被杀、
#   内存世界 (WorldState) 丢失，演化中断。详见 SANDBOX_SPEC.md §0 / §2。
# 若开发期确需热重载，请自行临时加 --reload 并接受"世界会被重置"的代价。

cd "$(dirname "$0")" || exit 1
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8787 --no-access-log
