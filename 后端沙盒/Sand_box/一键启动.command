#!/bin/bash
# macOS 双击启动：沙箱 + Skills + Gateway + Cron + 打开控制页
cd "$(dirname "$0")" || exit 1
export SANDBOX_HEARTBEAT_STATE="${SANDBOX_HEARTBEAT_STATE:-$PWD/.run/heartbeat-state.json}"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     Sand_box · OpenClaw 沙箱模拟 一键启动         ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

chmod +x scripts/start-all.sh scripts/stop-all.sh 2>/dev/null || true
./scripts/start-all.sh --all

echo ""
read -r -p "按回车键关闭此窗口…" _
