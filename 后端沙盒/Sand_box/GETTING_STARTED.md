# 全天候私人管家 · 启动与演示指南

## 前置条件

| 依赖 | 用途 |
|---|---|
| Python 3.10+ | 沙箱后端 |
| Node.js 18+ | Skill 脚本 |
| OpenClaw CLI | Agent + Cron（可选）|
| curl | 健康检查 |

默认端口：沙箱 **8787** · Gateway **18789**

---

## 一键启动（推荐）

```bash
cd Jensen_Song
chmod +x scripts/start-all.sh
./scripts/start-all.sh
```

可选：

```bash
./scripts/start-all.sh --gateway --cron --demo
```

| 参数 | 作用 |
|---|---|
| `--gateway` | 后台启动 `openclaw gateway` |
| `--cron` | 注册管家心跳（每 30s）|
| `--demo` | 跑 `demo/e2e-story.js` |

---

## 手动启动顺序

### 1. 沙箱

```bash
cd dynamic-sandbox && ./run.sh
curl http://127.0.0.1:8787/health
```

### 2. OpenClaw Gateway（另开终端）

```bash
openclaw gateway --port 18789
```

### 3. 挂载 Skills

```bash
cd skills && ./install.sh
```

### 4. 管家心跳

```bash
bash skills/sandbox-heartbeat/install-cron.sh
```

---

## 健康检查

```bash
node scripts/health-check.js           # 沙箱 API
node scripts/health-check.js --skills  # 沙箱 + 全部 Skill
```

---

## 端到端演示

```bash
node demo/e2e-story.js
```

三条故事：搜日料 → 取号叫号 → 下雨联动出行/娱乐。

OpenClaw 对话测试见 [DEMO.md](./DEMO.md)。

## 最终验收

```bash
node scripts/acceptance-check.js --boot
```

对照六项标准见 [ACCEPTANCE.md](./ACCEPTANCE.md)。

---

## 停止

```bash
kill $(cat .run/sandbox.pid)   # 若由 start-all 启动
bash skills/sandbox-heartbeat/uninstall-cron.sh
```
