---
name: food-guide
description: 本地餐饮推荐与排队取号。用户提到吃饭、餐厅、美食、推荐、排队时必须 exec 本 Skill 脚本，禁止联网搜索。
user-invocable: true
disable-model-invocation: false
metadata: {"openclaw":{"requires":{"bins":["node"]}}}
---

# Food Guide 本地餐饮助手

## Agent 执行规则（必读）

1. **必须用 `exec` 运行脚本**，不要读 mock JSON、不要联网搜餐厅。
2. 脚本返回 JSON，**先把 `summary` 复述给用户**，需要细节再看 `data` / `restaurants` / `ticket`。
3. 沙箱需已启动：`cd dynamic-sandbox && ./run.sh`（默认 `http://127.0.0.1:8787`）。

## 脚本 1：搜索餐厅

```bash
node {baseDir}/scripts/search-restaurants.js --area 望京 --cuisine 日料 --budget 300 --people 2
```

选项：`--area` `--cuisine` `--tag` `--budget` `--people` `--sort wait|rating|price` `--limit 5` `--id r004`

## 脚本 2：排队取号

```bash
node {baseDir}/scripts/queue-number.js take --restaurant-id <id> --people 2 --name <姓名>
node {baseDir}/scripts/queue-number.js status --queue-code <排队号>
node {baseDir}/scripts/queue-number.js cancel --queue-code <排队号>
```

排队由沙箱后台 tick 推进，用 `status` 查最新进度。`restaurant-id` 从搜索结果获取，不要向用户暴露 id。

**取号成功后**：脚本会自动注册「盯号」；告知用户「叫号时我会主动提醒」。确保已安装 `sandbox-heartbeat` Cron（`install-cron.sh`）。用户无需反复问「排队进度」，除非主动查询。

## 自测

```bash
node {baseDir}/scripts/verify.js
```

## 跨 Skill 上下文

用户选定餐厅后，在回复中保留：**餐厅名、地址、商圈、人数、预算、预计用餐结束时间**，供 mobility-planner / entertainment-scout 继承。
