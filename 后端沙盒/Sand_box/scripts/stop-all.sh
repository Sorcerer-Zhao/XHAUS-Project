#!/usr/bin/env bash
# 一键停止：沙箱 +（可选）本脚本启动的 Gateway
#
# 用法:
#   ./scripts/stop-all.sh           # 仅停沙箱
#   ./scripts/stop-all.sh --gateway # 额外停 .run/gateway.pid（若存在）
#   ./scripts/stop-all.sh --cron    # 卸载 sandbox-heartbeat Cron

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.run"
STOP_GATEWAY=false
UNINSTALL_CRON=false

for arg in "$@"; do
  case "$arg" in
    --gateway) STOP_GATEWAY=true ;;
    --cron) UNINSTALL_CRON=true ;;
  esac
done

stop_pid_file() {
  local name="$1"
  local file="$2"
  if [[ ! -f "$file" ]]; then
    echo "ℹ️  无 $name pid 文件: $file"
    return 0
  fi
  local pid
  pid="$(cat "$file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    echo "✅ 已停止 $name (pid $pid)"
  else
    echo "ℹ️  $name 进程已不存在 (pid $pid)"
  fi
  rm -f "$file"
}

echo "▶ 停止 Sand_box 服务 ..."
stop_pid_file "沙箱" "$RUN_DIR/sandbox.pid"

# 若 8787 仍被占用（非本脚本启动的进程），尝试释放
if lsof -nP -iTCP:8787 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠️  端口 8787 仍被占用。若需强制停止: lsof -ti :8787 | xargs kill"
fi

if $STOP_GATEWAY; then
  stop_pid_file "Gateway" "$RUN_DIR/gateway.pid"
  echo "ℹ️  若 Gateway 由 launchctl/系统服务管理，请用: openclaw gateway stop"
fi

if $UNINSTALL_CRON && command -v openclaw >/dev/null 2>&1; then
  bash "$ROOT/skills/sandbox-heartbeat/uninstall-cron.sh" || true
fi

echo "完成。"
