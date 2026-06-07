#!/usr/bin/env bash
set -euo pipefail
JOB_NAME="sandbox-heartbeat"
openclaw cron rm "$JOB_NAME" 2>/dev/null && echo "已移除 Cron: $JOB_NAME" || echo "Cron 不存在或已移除: $JOB_NAME"
