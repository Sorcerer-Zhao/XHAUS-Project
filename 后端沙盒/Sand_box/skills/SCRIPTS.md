# OpenClaw Skill 可执行脚本索引（Phase 3）

**Agent 规则：必须通过 `exec` 运行下列脚本获取数据，禁止自行编造或联网搜索。**
脚本输出 JSON，优先阅读顶层的 `summary` 字段向用户复述，细节查 `data` 或同级结构化字段。

环境变量：`SANDBOX_URL`（默认 `http://127.0.0.1:8787`）

| 能力 | Skill | 脚本 | 验证 |
|---|---|---|---|
| 搜餐厅 | food-guide | `scripts/search-restaurants.js` | `scripts/verify.js` |
| 排队 | food-guide | `scripts/queue-number.js` | ↑ |
| 天气 | weather | `scripts/weather-query.js` | `scripts/verify.js` |
| 出行 | mobility-planner | `scripts/mobility-plan.js` | `scripts/verify.js` |
| 娱乐 | entertainment-scout | `scripts/entertainment-query.js` | `scripts/verify.js` |
| 管家心跳 | sandbox-heartbeat | `scripts/poll-events.js` | `scripts/verify.js` |

全量验证：`node verify-phase2.js`（需先 `./dynamic-sandbox/run.sh`）

管家心跳 Cron：`bash sandbox-heartbeat/install-cron.sh`（每 30s）
状态文件：`~/.openclaw/sandbox-heartbeat/state.json`（`last_seq`）

## 统一输出格式

```json
{
  "success": true,
  "action": "search_restaurants",
  "summary": "自然语言摘要，可直接复述",
  "data": { },
  "source": "sandbox",
  "sandbox": "http://127.0.0.1:8787"
}
```
