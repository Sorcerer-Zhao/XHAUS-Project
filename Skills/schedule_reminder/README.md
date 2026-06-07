# schedule_reminder

Cursor Agent Skill：从对话中识别日程意图，提取结构化信息，持久化到本地日程表，并通过 **Cron 主动提醒**、**Apple 提醒事项** 与 **Apple 日历** 实现三层提醒。

适用于中文场景，如「提醒我」「安排一下」「周四中午去…」「明天开会」等表达。

## 功能

- **意图识别**：从自然语言中提取事件、日期、时间、地点、出发地、交通方式等字段
- **偏好推断**：根据事件类型推断 `masterPreference`（重要程度与提醒语气）
- **来源追踪**：记录 `reminder-source`（提议人、渠道、群组），提醒时路由回原始会话
- **三层提醒**：
  - T-1 天：提前知会
  - T-2 小时：准备出发
  - T-1 小时：最后催促
- **原生联动**：通过 `remindctl` 写入 Apple 提醒事项，通过 AppleScript 写入 iCloud「个人」日历
- **自动清理**：超过 14 天的历史条目在写入时自动移除

## 环境要求

- **macOS**（Apple 提醒事项、日历、osascript）
- **remindctl**（管理 Apple 提醒事项 CLI）
  - 首次使用若提示权限未授权，运行：`remindctl authorize`
- **iCloud 日历**：需存在名为「个人」的 iCloud 日历（非本地「日程」）
- 支持 Cron 的 Agent 运行时（如 OpenClaw / Cursor Automations），用于定时主动推送

## 安装

### 个人 Skill（全项目可用）

```bash
cp -r schedule_reminder ~/.cursor/skills/schedule-reminder
```

### 项目 Skill（随仓库共享）

```bash
mkdir -p .cursor/skills
cp -r schedule_reminder .cursor/skills/schedule-reminder
```

Agent 通过根目录 **`SKILL.md`** 自动激活。触发词包括：提醒我、安排、出发、周四、明天、下周等。

## 使用示例

用户说：

> 周四中午去猛古里吃自助，从北交出发

Skill 将：

1. 解析并补全字段（日期、默认午餐时间、地点等）
2. 视情况确认重要程度（「这个约重要吗？」）
3. 写入 `memory/schedule.json`
4. 创建 3 个 Cron 任务（提前 1 天 / 2 小时 / 1 小时）
5. 添加 Apple 提醒事项到「日程提醒」列表
6. 在 iCloud「个人」日历创建事件

用户也可查询：

- 「我今天有什么安排」
- 「明天有什么日程」

## 目录结构

```
schedule_reminder/
├── SKILL.md                        # 技能主文档（Agent 读取）
├── references/
│   └── schedule-format.md          # schedule.json 字段规范
└── README.md
```

运行时数据（不纳入 git）：

```
memory/
└── schedule.json                   # 日程条目与提醒 ID 追踪
```

完整 JSON 格式见 [references/schedule-format.md](references/schedule-format.md)。

## 提醒路由

根据 `reminder-source` 将 Cron 触发的消息送回来源渠道：

| 渠道 | 行为 |
|------|------|
| `webchat` | 在当前 Web 会话中提醒 |
| `feishu`（群聊） | 推送到对应群组，并 @ 提议人 |
| `feishu`（私聊） | 飞书私信提醒 |
| `weixin` | 使用 @username 格式提及 |

## 本机路径（不纳入 git）

| 路径 | 用途 |
|------|------|
| `memory/schedule.json` | 日程条目、Cron / 提醒 / 日历 ID |
| Apple 提醒事项「日程提醒」列表 | 系统级推送提醒 |
| iCloud「个人」日历 | 跨设备同步的日历事件 |

## 权限

首次使用提醒事项或日历时，需在 **系统设置 → 隐私与安全性** 中允许终端或 Cursor 访问「提醒事项」与「日历」。

## License

Private / 按需自行补充。
