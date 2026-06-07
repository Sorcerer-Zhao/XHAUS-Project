#!/usr/bin/env bash
# XHAUS 一键安装脚本（macOS）
# 功能：在仓库 RUNXHAUS/ 下克隆 Web 前端 → 配置环境 → 简易 OpenClaw → 启动并打开网页
#
# 用法（在 XHAUS-Project 仓库根目录）：
#   chmod +x scripts/setup-xhaus-mac.sh
#   ./scripts/setup-xhaus-mac.sh
#
# 可选环境变量：
#   XHAUS_HOME=<路径>           运行目录（默认 <仓库根>/RUNXHAUS）
#   SKIP_OPENCLAW_ONBOARD=1     跳过 OpenClaw 首次引导（需已配置过）

set -euo pipefail

# ── 配置 ──────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XHAUS_HOME="${XHAUS_HOME:-$REPO_ROOT/RUNXHAUS}"
WEB_REPO="https://github.com/hareonna-hina/XHUAS_WEBPAGE.git"
WEB_DIR="$XHAUS_HOME/XHUAS_WEBPAGE"
RUN_DIR="$XHAUS_HOME/.run"
GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
WEB_PORT="${PORT:-3000}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"

# ── 输出 ──────────────────────────────────────────────────────────────
info()  { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[ OK ]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "未找到命令: $1，请先安装后再运行本脚本"
}

port_listening() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_port() {
  local port=$1 max=${2:-30} i
  for ((i = 1; i <= max; i++)); do
    port_listening "$port" && return 0
    sleep 1
  done
  return 1
}

# ── 1. 检查依赖 ───────────────────────────────────────────────────────
info "检查系统依赖 …"
need_cmd git
need_cmd node
need_cmd npm

PYTHON=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  fail "未找到 Python 3.10+，请从 https://www.python.org 安装"
fi

NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]")"
[[ "$NODE_MAJOR" -ge 18 ]] || fail "需要 Node.js 18+，当前: $(node -v)"

ok "Node $(node -v) · Python $("$PYTHON" --version 2>&1)"

# ── 2. 创建目录 ───────────────────────────────────────────────────────
info "创建运行目录: $XHAUS_HOME （位于仓库 $REPO_ROOT 下）"
mkdir -p "$XHAUS_HOME" "$RUN_DIR"

# ── 3. 克隆 / 更新 Web 前端仓库 ─────────────────────────────────────
if [[ -d "$WEB_DIR/.git" ]]; then
  info "仓库已存在，拉取最新代码 …"
  git -C "$WEB_DIR" pull --ff-only || warn "git pull 失败，继续使用本地版本"
else
  info "克隆 Web 前端仓库 …"
  git clone "$WEB_REPO" "$WEB_DIR"
fi
ok "Web 前端路径: $WEB_DIR"

# ── 4. 安装 Node 依赖 ─────────────────────────────────────────────────
info "安装 Web 后端依赖 (npm install) …"
(cd "$WEB_DIR/backend" && npm install)
ok "npm 依赖安装完成"

# ── 5. 安装 Python 依赖 ─────────────────────────────────────────────
info "安装 XHAUS Python 依赖 …"
"$PYTHON" -m pip install -q -r "$WEB_DIR/XHAUS/requirements.txt"

if [[ -f "$WEB_DIR/Satellite/meta_skill/requirements.txt" ]]; then
  info "安装 Satellite Python 依赖 …"
  "$PYTHON" -m pip install -q -r "$WEB_DIR/Satellite/meta_skill/requirements.txt"
fi
ok "Python 依赖安装完成"

# ── 6. 生成 backend/.env ─────────────────────────────────────────────
ENV_FILE="$WEB_DIR/backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  info "生成 backend/.env …"
  cp "$WEB_DIR/backend/.env.example" "$ENV_FILE"
fi

JWT_SECRET="$(openssl rand -hex 32 2>/dev/null || "$PYTHON" -c 'import secrets; print(secrets.token_hex(32))')"

# 写入关键配置（macOS sed）
set_env() {
  local key=$1 val=$2 file=$3
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i '' "s|^${key}=.*|${key}=${val}|" "$file"
  else
    echo "${key}=${val}" >> "$file"
  fi
}

set_env JWT_SECRET "$JWT_SECRET" "$ENV_FILE"
set_env PORT "$WEB_PORT" "$ENV_FILE"
set_env XHUAS_PROJECT_ROOT "$WEB_DIR" "$ENV_FILE"
set_env XHAUS_PYTHON "$PYTHON" "$ENV_FILE"
set_env OPENCLAW_CHAT_COMPLETIONS_URL "http://127.0.0.1:${GATEWAY_PORT}/v1/chat/completions" "$ENV_FILE"

ok ".env 已配置（JWT_SECRET 已自动生成）"

# ── 7. 简易 OpenClaw 配置 ─────────────────────────────────────────────
setup_openclaw() {
  info "配置 OpenClaw …"

  if ! command -v openclaw >/dev/null 2>&1; then
    info "安装 OpenClaw CLI (npm install -g openclaw@latest) …"
    npm install -g openclaw@latest
  fi
  ok "OpenClaw CLI: $(openclaw --version 2>/dev/null || echo 'installed')"

  OPENCLAW_CONFIG="$HOME/.openclaw/openclaw.json"
  if [[ ! -f "$OPENCLAW_CONFIG" ]] && [[ "${SKIP_OPENCLAW_ONBOARD:-}" != "1" ]]; then
    warn "检测到首次使用 OpenClaw，需要完成约 2 分钟的简易引导："
    echo "  · 选择模型提供商（如 DeepSeek / OpenAI / Anthropic）"
    echo "  · 填入对应的 API Key"
    echo "  · 保持 Gateway 端口为 ${GATEWAY_PORT}（默认即可）"
    echo ""
    read -r -p "按 Enter 开始 OpenClaw 引导，或 Ctrl+C 取消 …"
    openclaw onboard --install-daemon
  elif [[ ! -f "$OPENCLAW_CONFIG" ]]; then
    warn "已跳过 OpenClaw 引导，请确保 ~/.openclaw 已手动配置"
  else
    ok "OpenClaw 配置已存在: $OPENCLAW_CONFIG"
  fi

  if port_listening "$GATEWAY_PORT"; then
    ok "OpenClaw Gateway 已在端口 ${GATEWAY_PORT} 运行"
    return 0
  fi

  info "启动 OpenClaw Gateway (端口 ${GATEWAY_PORT}) …"
  # 优先尝试系统服务，失败则后台前台进程
  if openclaw gateway restart >/dev/null 2>&1; then
    :
  elif openclaw gateway install --force >/dev/null 2>&1 && openclaw gateway restart >/dev/null 2>&1; then
    :
  else
    nohup openclaw gateway --port "$GATEWAY_PORT" \
      >"$RUN_DIR/openclaw-gateway.log" 2>&1 &
    echo $! >"$RUN_DIR/openclaw-gateway.pid"
  fi

  if wait_port "$GATEWAY_PORT" 25; then
    ok "OpenClaw Gateway 已启动 → ws://127.0.0.1:${GATEWAY_PORT}"
  else
    warn "Gateway 未能及时监听 ${GATEWAY_PORT}，请查看日志: $RUN_DIR/openclaw-gateway.log"
    warn "可手动运行: openclaw gateway --port ${GATEWAY_PORT}"
  fi
}

setup_openclaw

# ── 8. 启动 Web 后端 ──────────────────────────────────────────────────
if port_listening "$WEB_PORT"; then
  warn "端口 ${WEB_PORT} 已被占用，尝试结束旧进程 …"
  lsof -tiTCP:"$WEB_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 1
fi

if port_listening "$WEB_PORT"; then
  warn "端口 ${WEB_PORT} 仍被占用，请手动结束后重新运行本脚本"
else
  info "启动 Web 后端 (端口 ${WEB_PORT}) …"
  nohup npm start --prefix "$WEB_DIR/backend" \
    >"$RUN_DIR/web-backend.log" 2>&1 &
  echo $! >"$RUN_DIR/web-backend.pid"

  if wait_port "$WEB_PORT" 30; then
    ok "Web 后端已启动"
  else
    fail "Web 后端启动失败，请查看: $RUN_DIR/web-backend.log"
  fi
fi

# ── 9. 打开浏览器 ─────────────────────────────────────────────────────
info "打开 Web 界面 …"
sleep 1
open "$WEB_URL" 2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════════════"
ok "XHAUS 安装完成！"
echo ""
echo "  Web 界面:     $WEB_URL"
echo "  OpenClaw:     ws://127.0.0.1:${GATEWAY_PORT}"
echo "  安装目录:     $XHAUS_HOME"
echo "  日志目录:     $RUN_DIR"
echo ""
echo "  首次使用步骤："
echo "    1. 在网页点击「开始使用」"
echo "    2. WebSocket 地址填入: ws://127.0.0.1:${GATEWAY_PORT}"
echo "    3. 选择人格预设（如 Franziska、Emma）后开始对话"
echo ""
echo "  停止服务："
echo "    kill \$(cat $RUN_DIR/web-backend.pid) 2>/dev/null"
echo "    kill \$(cat $RUN_DIR/openclaw-gateway.pid) 2>/dev/null"
echo "    openclaw gateway stop 2>/dev/null"
echo "════════════════════════════════════════════════════════════"
