# 演示剧本（90 秒）

## 准备

```bash
./scripts/start-all.sh --gateway --cron
node demo/e2e-story.js
```

## 三幕台词

### 第一幕：搜日料

> 望京附近有什么日料？两个人，预算 300。

Agent exec `search-restaurants.js`，复述 `summary`（评分、等位、推荐）。

### 第二幕：取号叫号

> 帮我在松子那家排个号，2 个人。

返回 `queue_code` 和前方桌数。Cron 心跳或注入叫号后主动提醒就座。

### 第三幕：下雨联动

> 下雨了，从望京去三里屯怎么走？有什么室内活动？

预期：推荐地铁、室内电影；户外公园被降权。

控场注入雨天：

```bash
curl -X POST http://127.0.0.1:8787/admin/inject \
  -H 'Content-Type: application/json' -d '{"kind":"rain"}'
```

## 自动化演示

```bash
node demo/e2e-story.js
```

复位：`curl -X POST http://127.0.0.1:8787/admin/reset -H 'Content-Type: application/json' -d '{"seed":42}'`
