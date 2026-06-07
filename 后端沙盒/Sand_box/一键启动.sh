#!/usr/bin/env bash
# 终端一键启动（等价于 一键启动.command）
ROOT="$(cd "$(dirname "$0")" && pwd)"
export SANDBOX_HEARTBEAT_STATE="${SANDBOX_HEARTBEAT_STATE:-$ROOT/.run/heartbeat-state.json}"
exec "$ROOT/scripts/start-all.sh" --all "$@"
