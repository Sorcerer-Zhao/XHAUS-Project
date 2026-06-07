---
name: sandbox-heartbeat
description: 管家心跳：轮询沙箱 /events 增量事件，在用户不说话时主动提醒排队/天气/出行等。由 Cron 每30秒触发或手动运行。
user-invocable: true
disable-model-invocation: false
metadata: {"openclaw":{"requires":{"bins":["node"]}}}
---

# Sandbox Heartbeat 管家心跳

## Agent 执行规则（必读）

1. **定时任务**：每 30 秒运行 `poll-events.js`（推荐 OpenClaw Cron，见 `install-cron.sh`；2026.6+ 使用 `isolated` session 以便 Agent 可 exec）。
2. 读输出 JSON 的 **`summary`**；若 `data.reminders` 非空，**必须用 message 工具推送**每条 `reminder.text`（尤其 `queue.called` 叫号）。
3. `reminders` 为空时**保持静默**，不要打扰用户。
4. 取号后 `watch-queue.json` 会记录票号；心跳除 `/events` 外还会轮询 `/queue/status`，防止漏叫号。
4. 幂等：脚本自动维护 `last_seq`（`~/.openclaw/sandbox-heartbeat/state.json`）。
5. 沙箱需运行：`cd dynamic-sandbox && ./run.sh`

## 脚本 1：单次轮询（Cron 调用这个）

```bash
node {baseDir}/scripts/poll-events.js
```

选项：`--dry-run` `--reset` `--status` `--since N`

## 脚本 2：本地循环（开发/演示，无需 Cron）

```bash
node {baseDir}/scripts/run-loop.js --interval 30
```

## 脚本 3：SSE 监听（可选）

```bash
node {baseDir}/scripts/stream-once.js --seconds 15
```

## 关注的事件类型

| type | 用户提醒场景 |
|---|---|
| `queue.threshold` | 前面只剩几桌，提醒准备出发 |
| `queue.called` | 已叫号，催促就座 |
| `restaurant.full` | 餐厅满座，建议换店 |
| `weather.changed` | 下雨/放晴，调整娱乐和出行 |
| `venue.closed` | 户外场所关闭，推荐室内替代 |
| `mobility.surge` | 打车加价，建议地铁 |

## 安装 OpenClaw Cron（每 30 秒）

```bash
bash {baseDir}/install-cron.sh
```

卸载：`bash {baseDir}/uninstall-cron.sh`

## 自测

```bash
node {baseDir}/scripts/verify.js
```
