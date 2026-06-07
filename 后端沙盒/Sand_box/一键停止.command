#!/bin/bash
# macOS 双击停止：沙箱 + 本脚本启动的 Gateway + Cron
cd "$(dirname "$0")" || exit 1

chmod +x scripts/stop-all.sh 2>/dev/null || true
./scripts/stop-all.sh --gateway --cron

echo ""
read -r -p "按回车键关闭此窗口…" _
