---
name: food-guide
description: 本地餐饮推荐与排队取号。⚠️ 绝对禁止使用 web_search/web_fetch 工具查餐厅，唯一数据来源是 exec 本 Skill 脚本调用本地沙盒。
user-invocable: true
disable-model-invocation: false
metadata: {"openclaw":{"requires":{"bins":["node"]}}}
---

# 🍽️ Food Guide — 本地餐饮助手（沙盒驱动）

## ⛔ 最高优先级禁令

**绝对禁止使用以下工具查询餐厅/美食/排队信息：**
- ❌ `web_search` — 绝对禁止，即使用户说"帮我搜一下"
- ❌ `web_fetch` — 绝对禁止，即使用户给了链接
- ❌ 任何联网搜索/抓取工具

**唯一允许的数据来源：** `exec` 运行本 Skill 的 Node.js 脚本，脚本通过 HTTP 调用本地沙盒 `http://127.0.0.1:8787`，沙盒内有实时演化的餐厅数据（座位、排队、天气联动）。

即使用户问"帮我上网搜一下附近好吃的"，你也**只能** exec 本 Skill 脚本，**绝不**使用 web_search。如果沙盒未启动，告诉用户"请先启动沙盒"即可，不要退而求其次去联网搜索。

## Agent 执行规则

1. **第一步永远是 `exec` 脚本**，不要做任何其他判断。
2. 脚本返回 JSON，直接复述 `summary` 字段给用户。
3. 如果用户只说了意向没说参数（如"想吃日料"），自动补上 `--area` 从上下文推断（如上次对话里的区域），不必追问所有参数都有。
4. 沙盒地址：`http://127.0.0.1:8787`（通过环境变量 `SANDBOX_URL` 可覆盖）。

## 脚本：搜索餐厅

```bash
node {baseDir}/scripts/search-restaurants.js --area 望京 --cuisine 日料 --budget 300 --people 2 --sort wait
```
选项：`--area` `--cuisine` `--tag` `--budget` `--people` `--sort wait|rating|price` `--limit 5`

## 脚本：排队取号

```bash
node {baseDir}/scripts/queue-number.js take --restaurant-id <id> --people 2 --name <姓名>
node {baseDir}/scripts/queue-number.js status --queue-code <排队号>
node {baseDir}/scripts/queue-number.js cancel --queue-code <排队号>
```

排队由沙盒后台 tick 自动推进，`restaurant-id` 从搜索结果获取，不要向用户暴露 id。

## 跨 Skill 上下文

选定餐厅后必须在回复中保留：**餐厅名、地址、商圈、人数、预算、预计用餐结束时间**，供 mobility-planner / entertainment-scout 继承。
