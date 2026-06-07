#!/usr/bin/env bash
# 注册 OpenClaw Cron：每 30 秒运行管家心跳
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
POLL_SCRIPT="$SCRIPT_DIR/scripts/poll-events.js"
JOB_NAME="sandbox-heartbeat"

if [[ ! -f "$POLL_SCRIPT" ]]; then
  echo "找不到 $POLL_SCRIPT" >&2
  exit 1
fi

MSG="$(cat <<EOF
【管家心跳】请用 exec 运行：
node "$POLL_SCRIPT"

规则：
1. 用 exec 运行上述脚本，解析 JSON。
2. 若 data.reminders 非空：必须用 message 工具把每条 reminder.text 发给用户（排队叫号、快到号等），不要只写 HEARTBEAT_OK。叫号(queue.called)最紧急，立即推送。
3. 若 reminders 为空：回复 HEARTBEAT_OK（静默）。
4. 脚本已盯号轮询 /queue/status，即使 /events 漏了也会补提醒。
5. 用户需曾在当前渠道说过话，message 才能送达。
EOF
)"

# 若已存在则先删除（按名称可能有多条重复，逐个按 ID 清掉）
if openclaw cron list --json 2>/dev/null | python3 -c "
import sys,json
try:
  data=json.load(sys.stdin)
  jobs=data if isinstance(data,list) else data.get('jobs',[])
  for j in jobs:
    if j.get('name')=='$JOB_NAME' and j.get('id'):
      print(j['id'])
except Exception:
  pass
" 2>/dev/null | while read -r jid; do
  echo "移除已有 Cron: $JOB_NAME ($jid)"
  openclaw cron rm "$jid" 2>/dev/null || true
done
# 兜底：按名称再删一次
openclaw cron rm "$JOB_NAME" 2>/dev/null || true

# OpenClaw 2026.6+：--session main 必须用 --system-event，且不会执行 shell。
# 管家心跳需要 Agent exec 脚本，因此用 isolated + --message。
echo "注册 Cron: $JOB_NAME (every 30s, session=isolated)"
ADD_OUT="$(openclaw cron add \
  --name "$JOB_NAME" \
  --every 30s \
  --session isolated \
  --wake now \
  --announce \
  --message "$MSG" 2>&1)" || { echo "$ADD_OUT" >&2; exit 1; }

echo "$ADD_OUT"

JOB_ID="$(echo "$ADD_OUT" | sed -n 's/.*"id": "\([^"]*\)".*/\1/p' | head -1)"
if command -v python3 >/dev/null 2>&1; then
  JOB_ID="$(printf '%s' "$ADD_OUT" | python3 -c "import sys,json,re
t=sys.stdin.read()
m=re.search(r'\{[\s\S]*\}', t)
print(json.loads(m.group())['id'] if m else '')" 2>/dev/null || true)"
fi

echo ""
echo "完成。查看: openclaw cron list"
if [[ -n "$JOB_ID" ]]; then
  echo "立即试跑: openclaw cron run $JOB_ID"
else
  echo "立即试跑: openclaw cron run <job-id>   # 从 cron list 第一列复制 ID"
fi
echo ""
echo "提示：delivery 为 announce -> last 时，需先在与 Gateway 的对话里发过至少一条消息，"
echo "      否则主动提醒无投递通道。也可先手动测脚本："
echo "      node \"$POLL_SCRIPT\""
