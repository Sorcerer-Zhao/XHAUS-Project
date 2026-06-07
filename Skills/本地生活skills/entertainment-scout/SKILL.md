---
name: entertainment-scout
description: 饭后娱乐推荐（电影/KTV/酒吧/密室等）。用户提到娱乐、消遣时必须 exec entertainment-query.js。
user-invocable: true
disable-model-invocation: false
metadata: {"openclaw":{"requires":{"bins":["node"]}}}
---

# Entertainment Scout

## Agent 执行规则（必读）

1. **必须用 `exec` 运行脚本**，不要联网搜索娱乐场所。
2. 读 JSON 的 **`summary`** 向用户推荐；详情在 `data.venues[]`。
3. 继承 food-guide 上下文：区域、用餐结束时间、人数、剩余预算。
4. 沙箱：`cd dynamic-sandbox && ./run.sh`

## 脚本：娱乐活动查询

```bash
node {baseDir}/scripts/entertainment-query.js --area 三里屯 --time 21:00 --people 2 --budget 200 --mood lively
```

选项：`--area` `--type` `--time` `--people` `--budget` `--mood quiet|lively|active|relaxed` `--limit 6`

（兼容旧名：`discover-entertainment.js`）

## 自测

```bash
node {baseDir}/scripts/verify.js
```
