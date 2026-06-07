# 全天候私人管家 · Jensen_Song

OpenClaw Agent + 动态沙箱端到端集成。

## 快速开始

**一键启动（推荐）：**

```bash
chmod +x 一键启动.sh 一键启动.command scripts/*.sh
./一键启动.sh
```

或在 Finder 中 **双击 `一键启动.command`**（macOS）。

```bash
./scripts/start-all.sh --all    # 同上：沙箱 + Skills + Gateway + Cron + 打开 UI
./scripts/start-all.sh --demo   # 额外跑端到端演示
./scripts/stop-all.sh --gateway --cron   # 停止
```

**最终验收：** `node scripts/acceptance-check.js --boot`（见 [ACCEPTANCE.md](./ACCEPTANCE.md)）

- 启动说明：[GETTING_STARTED.md](./GETTING_STARTED.md)
- 演示剧本：[DEMO.md](./DEMO.md)
- Skill 索引：[skills/SCRIPTS.md](./skills/SCRIPTS.md)

## 架构

```
用户 → OpenClaw → Skill 脚本 → :8787 沙箱 → 活的世界
                    ↑
           sandbox-heartbeat (Cron) → 主动提醒
```

## 目录

| 路径 | 说明 |
|---|---|
| `dynamic-sandbox/` | FastAPI 世界引擎 |
| `skills/` | OpenClaw Skills |
| `scripts/` | 启动与健康检查 |
| `demo/` | 端到端故事演示 |
