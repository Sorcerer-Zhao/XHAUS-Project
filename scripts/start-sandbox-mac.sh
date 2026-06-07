#!/usr/bin/env bash
# XHAUS 动态沙盒一键启动（macOS）
# 在仓库根目录运行，委托 后端沙盒/Sand_box/scripts/start-all.sh
#
# 用法：
#   chmod +x scripts/start-sandbox-mac.sh
#   ./scripts/start-sandbox-mac.sh              # 默认：沙盒 + Skills + Gateway + Cron
#   ./scripts/start-sandbox-mac.sh --demo       # 额外跑端到端演示
#   ./scripts/start-sandbox-mac.sh --gateway    # 仅额外启动 Gateway（不加 --all）
#
# 停止：./scripts/stop-sandbox-mac.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SANDBOX_ROOT="$REPO_ROOT/后端沙盒/Sand_box"

info()  { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -d "$SANDBOX_ROOT" ]] || fail "找不到沙盒目录: $SANDBOX_ROOT"

info "沙盒目录: $SANDBOX_ROOT"

chmod +x "$SANDBOX_ROOT/scripts/"*.sh 2>/dev/null || true
chmod +x "$SANDBOX_ROOT/skills/install.sh" 2>/dev/null || true
chmod +x "$SANDBOX_ROOT/skills/sandbox-heartbeat/"*.sh 2>/dev/null || true
[[ -f "$SANDBOX_ROOT/一键启动.sh" ]] && chmod +x "$SANDBOX_ROOT/一键启动.sh" || true

ARGS=("$@")
if [[ ${#ARGS[@]} -eq 0 ]]; then
  ARGS=(--all)
fi

exec bash "$SANDBOX_ROOT/scripts/start-all.sh" "${ARGS[@]}"
