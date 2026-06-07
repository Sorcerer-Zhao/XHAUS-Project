#!/usr/bin/env bash
# 一键启动：沙箱 → 健康检查 → 挂载 Skills →（可选）Gateway / Cron / 演示
#
# 用法:
#   ./scripts/start-all.sh              # 启动沙箱 + 挂 skills + 健康检查
#   ./scripts/start-all.sh --all        # 完整 OpenClaw 模拟（gateway + cron + 打开 UI）
#   ./scripts/start-all.sh --cron       # 额外注册管家心跳 Cron
#   ./scripts/start-all.sh --demo       # 启动后跑端到端演示
#   ./scripts/start-all.sh --gateway    # 检测/启动 OpenClaw Gateway
#   ./scripts/start-all.sh --open-ui    # 启动完成后打开 Gateway 控制页

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.run"
PID_FILE="$RUN_DIR/sandbox.pid"
LOG_FILE="$RUN_DIR/sandbox.log"
GATEWAY_PID_FILE="$RUN_DIR/gateway.pid"
GATEWAY_LOG="$RUN_DIR/gateway.log"
SANDBOX_PORT="${SANDBOX_PORT:-8787}"
GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
GATEWAY_URL="http://127.0.0.1:${GATEWAY_PORT}"

WITH_CRON=false
WITH_DEMO=false
WITH_GATEWAY=false
WITH_OPEN_UI=false
for arg in "$@"; do
  case "$arg" in
    --all)
      WITH_GATEWAY=true
      WITH_CRON=true
      WITH_OPEN_UI=true
      ;;
    --cron) WITH_CRON=true ;;
    --demo) WITH_DEMO=true ;;
    --gateway) WITH_GATEWAY=true ;;
    --open-ui) WITH_OPEN_UI=true ;;
  esac
done

gateway_listening() {
  lsof -nP -iTCP:"${GATEWAY_PORT}" -sTCP:LISTEN >/dev/null 2>&1
}

mkdir -p "$RUN_DIR"
# 心跳状态放在本项目 .run/ 下，避免与旧目录混淆（可被 SANDBOX_HEARTBEAT_STATE 覆盖）
export SANDBOX_HEARTBEAT_STATE="${SANDBOX_HEARTBEAT_STATE:-$RUN_DIR/heartbeat-state.json}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少命令: $1" >&2; exit 1; }
}

need_cmd python3
need_cmd node
need_cmd curl

echo "╔══════════════════════════════════════════════════╗"
echo "║  全天候私人管家 · 一键启动                        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. 沙箱 ──
if curl -sf "http://127.0.0.1:${SANDBOX_PORT}/health" >/dev/null 2>&1; then
  echo "✅ 沙箱已在运行 (:${SANDBOX_PORT})"
else
  echo "▶ 启动 dynamic-sandbox (:${SANDBOX_PORT}) ..."
  need_cmd python3
  python3 -m pip install -q -r "$ROOT/dynamic-sandbox/requirements.txt" 2>/dev/null || true
  (
    cd "$ROOT/dynamic-sandbox"
    nohup python3 -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$SANDBOX_PORT" --no-access-log \
      >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    disown
  )
  for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${SANDBOX_PORT}/health" >/dev/null 2>&1; then
      echo "✅ 沙箱已启动 (pid $(cat "$PID_FILE"), log: $LOG_FILE)"
      break
    fi
    sleep 0.5
    if [[ $i -eq 30 ]]; then
      echo "❌ 沙箱启动超时，查看 $LOG_FILE" >&2
      exit 1
    fi
  done
fi

# 演示用：复位世界 + 加速时钟
curl -sf -X POST "http://127.0.0.1:${SANDBOX_PORT}/admin/reset" \
  -H 'Content-Type: application/json' -d '{"seed":42}' >/dev/null || true
curl -sf -X POST "http://127.0.0.1:${SANDBOX_PORT}/admin/clock" \
  -H 'Content-Type: application/json' -d '{"time_scale":30}' >/dev/null || true
echo "✅ 世界已复位 seed=42，倍速 30x（演示友好）"

# ── 2. 健康检查 ──
echo ""
echo "▶ 健康检查 ..."
node "$ROOT/scripts/health-check.js" || { echo "❌ 健康检查失败" >&2; exit 1; }

# ── 3. 挂载 Skills ──
echo ""
echo "▶ 挂载 Skills 到 OpenClaw workspaces ..."
bash "$ROOT/skills/install.sh"

# ── 4. Gateway（可选）──
GATEWAY_OK=false
if $WITH_GATEWAY; then
  if command -v openclaw >/dev/null 2>&1; then
    if gateway_listening; then
      echo "✅ OpenClaw Gateway 已在 :${GATEWAY_PORT}（无需重复启动）"
      GATEWAY_OK=true
    else
      echo "▶ 后台启动 OpenClaw Gateway :${GATEWAY_PORT} ..."
      nohup openclaw gateway --port "$GATEWAY_PORT" >>"$GATEWAY_LOG" 2>&1 &
      echo $! >"$GATEWAY_PID_FILE"
      for i in $(seq 1 20); do
        if gateway_listening; then
          echo "✅ Gateway 已启动 (pid $(cat "$GATEWAY_PID_FILE"), log: $GATEWAY_LOG)"
          GATEWAY_OK=true
          break
        fi
        sleep 0.5
      done
      if ! $GATEWAY_OK; then
        echo "❌ Gateway 启动失败。若端口被占用: openclaw gateway stop" >&2
        echo "   日志: $GATEWAY_LOG" >&2
      fi
    fi
  else
    echo "⚠️  未找到 openclaw CLI，请手动: openclaw gateway --port ${GATEWAY_PORT}"
  fi
else
  echo ""
  echo "ℹ️  OpenClaw Gateway 需另开终端，或运行: ./scripts/start-all.sh --all"
  echo "    openclaw gateway --port ${GATEWAY_PORT}"
fi

# ── 5. Cron（可选）──
if $WITH_CRON; then
  if command -v openclaw >/dev/null 2>&1; then
    echo ""
    bash "$ROOT/skills/sandbox-heartbeat/install-cron.sh"
  else
    echo "⚠️  跳过 Cron：未找到 openclaw"
  fi
fi

# ── 6. 演示（可选）──
if $WITH_DEMO; then
  echo ""
  node "$ROOT/demo/e2e-story.js"
fi

if $WITH_OPEN_UI && $GATEWAY_OK; then
  echo ""
  echo "▶ 打开 OpenClaw 控制页 ..."
  if command -v open >/dev/null 2>&1; then
    open "$GATEWAY_URL" || true
  fi
fi

echo ""
echo "══════════════════════════════════════════════════"
echo " ✅ 一键启动完成"
echo "──────────────────────────────────────────────────"
echo " 沙箱 API:   http://127.0.0.1:${SANDBOX_PORT}/docs"
echo " OpenClaw:   ${GATEWAY_URL}"
echo " 终端对话:   openclaw tui"
echo " 端到端演示: node $ROOT/demo/e2e-story.js"
echo " 完整检查:   node $ROOT/scripts/health-check.js --skills"
echo " 一键停止:   $ROOT/scripts/stop-all.sh"
echo "══════════════════════════════════════════════════"
echo ""
echo "💡 在 OpenClaw 里先发一条消息，Cron 主动提醒才能投递到对话。"
echo "   示例：「请用本地沙箱查询，望京附近有什么日料？两个人，预算300。」"
