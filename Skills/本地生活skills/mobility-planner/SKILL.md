---
name: mobility-planner
description: 出行方案对比（地铁/打车/步行）。用户提到怎么过去、路线、打车时必须 exec mobility-plan.js。
user-invocable: true
disable-model-invocation: false
metadata: {"openclaw":{"requires":{"bins":["node"]}}}
---

# Mobility Planner

## Agent 执行规则（必读）

1. **必须用 `exec` 运行脚本**，不要联网搜路线。
2. 读 JSON 的 **`summary`** 向用户推荐；`data.plans[]` 含各方案详情。
3. 若用户已通过 food-guide 选了餐厅，**自动用餐厅所在区域作 `--to`**。
4. 沙箱：`cd dynamic-sandbox && ./run.sh`

## 脚本：出行规划

```bash
node {baseDir}/scripts/mobility-plan.js --from 望京 --to 三里屯 --time 18:30
node {baseDir}/scripts/mobility-plan.js areas
```

选项：`--from` `--to` `--time HH:MM` `--mode all|subway|taxi|walk|bike`

（兼容旧名：`plan-route.js`）

## 自测

```bash
node {baseDir}/scripts/verify.js
```
