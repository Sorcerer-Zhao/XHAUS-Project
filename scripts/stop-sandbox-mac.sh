#!/usr/bin/env bash
# XHAUS 动态沙盒一键停止（macOS）
#
# 用法：
#   ./scripts/stop-sandbox-mac.sh
#   ./scripts/stop-sandbox-mac.sh --gateway --cron   # 默认已包含

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SANDBOX_ROOT="$REPO_ROOT/后端沙盒/Sand_box"

[[ -d "$SANDBOX_ROOT" ]] || { echo "找不到沙盒目录: $SANDBOX_ROOT" >&2; exit 1; }

exec bash "$SANDBOX_ROOT/scripts/stop-all.sh" --gateway --cron "$@"
