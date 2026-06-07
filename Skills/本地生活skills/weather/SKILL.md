---
name: weather
description: 查询实时天气与3日预报。用户提到天气、下雨、气温时必须 exec weather-query.js，禁止直连 open-meteo。
user-invocable: true
disable-model-invocation: false
metadata: {"openclaw":{"requires":{"bins":["node"]}}}
---

# Weather

## Agent 执行规则（必读）

1. **必须用 `exec` 运行脚本**，不要自己调 open-meteo。
2. 读 JSON 的 **`summary`** 字段向用户复述；详细数值在 `data.current` / `data.forecast3d`。
3. 沙箱：`cd dynamic-sandbox && ./run.sh`

## 脚本：天气查询

```bash
node {baseDir}/scripts/weather-query.js --area 望京
```

（兼容旧名：`get-weather.js`）

## 自测

```bash
node {baseDir}/scripts/verify.js
```
