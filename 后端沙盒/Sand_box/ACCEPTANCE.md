# Phase 7 · 最终验收标准

## 六项标准对照

| # | 标准 | 实现 | 验证 |
|---|---|---|---|
| 1 | OpenClaw 通过 Skill 调用沙箱 | 5 个 Skill + `_shared/sandbox-client.js`；`install.sh` 挂载到 workspace | `node scripts/acceptance-check.js` 项 [1] |
| 2 | 数据实时演化，非静态 mock | `WorldState` + `clock.py` 后台 tick；Skill 主路径只走 HTTP | 项 [2]：`tick_count` 增长 + `sim_now` |
| 3 | `/events` 可轮询或 SSE | `poll-events.js` / `stream-once.js`；后端 `GET /events` + `/events/stream` | 项 [3] |
| 4 | ≥3 条自然语言演示链路 | `demo/e2e-story.js` + `DEMO.md` 台词 | 项 [4] |
| 5 | 启动简单、文档明确、报错可读 | `start-all.sh`、`GETTING_STARTED.md`、`SandboxError` 中文 | 项 [5] |
| 6 | 结构清晰、易扩展 | `_shared` 三层 + 每 Skill 独立 `verify.js` + `SCRIPTS.md` | 项 [6] |

## 一键验收

```bash
# 沙箱已启动时
node scripts/acceptance-check.js

# 自动启动沙箱后验收
node scripts/acceptance-check.js --boot
```

等价手动步骤：

```bash
./scripts/start-all.sh
node scripts/health-check.js --skills
node demo/e2e-story.js
```

## OpenClaw 对话验收（人工）

1. `openclaw gateway --port 18789`
2. 确认 `~/.openclaw/openclaw.json` 的 `skills.load.allowSymlinkTargets` 含本项目 `skills/` 路径
3. 按 [DEMO.md](./DEMO.md) 三幕台词对话，Agent 应 `exec` 对应脚本并复述 `summary`

## 演示链路说明

| 链路 | 用户说法 | Skill 脚本 |
|---|---|---|
| 搜餐厅 | 望京附近日料，2人预算300 | `search-restaurants.js` |
| 取号叫号 | 帮我在某店排号 | `queue-number.js` + 心跳 `poll-events.js` |
| 下雨联动 | 下雨了怎么去三里屯/室内活动 | `weather-query.js` + `mobility-plan.js` + `entertainment-query.js` |

排队叫号、下雨场景在演示中可用 `/admin/inject` 加速（现场控场，见 `DEMO.md`）。

## 不在验收范围内的遗留

- `meituan-travel`、`crawl-*.js`、`assets/*.json` — 开发遗留，**不在 Skill 主路径**
- OpenClaw Gateway 对话 — 需本地 OpenClaw CLI，自动化仅覆盖 Skill→沙箱 HTTP
