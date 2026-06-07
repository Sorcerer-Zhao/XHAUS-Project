# phone_call

OpenClaw Skill：用 **Mac + iPhone** 完成餐厅订位电话预约。Agent 撰写口语化订位稿 → 用户确认 → 定时拨号或立即拨打 → 用户亲自通话。

不使用 Twilio / 云外呼。

## 功能

- 撰写并确认中文订位台词
- **定时预约**：写入 `current.json`，iPhone 快捷指令弹窗拨打
- **立即拨打**：Mac 通过 Continuity 发起呼叫（`dial.py`）
- 预约确认后自动：**通讯录**存商户电话、**iCloud 日历**写入用餐时间
- 可选 Pushcut 锁屏通知（见 `references/pushcut-popup-setup.md`）

## 环境要求

- macOS（生成快捷指令、写通讯录/日历、AirDrop）
- iPhone（运行快捷指令「预约拨号 v2.0」）
- Python 3.10+
- 系统「快捷指令」命令行：`shortcuts sign`（`setup.py --run` 会调用）

## 快速开始

### 1. 安装到 OpenClaw

将本仓库放到 OpenClaw skills 目录，或在工作区中引用本路径。Agent 通过根目录 **`SKILL.md`** 激活。

### 2. 首次引导

```bash
cd /path/to/phone_call
python setup.py --check-only
python setup.py --run
```

按 [references/onboarding.md](references/onboarding.md) 完成：

1. Mac 桌面 `~/Desktop/Openclaw-PhoneCall/`
2. iPhone「文件」→ 我的 iPhone → 新建 **`Shortcuts`** 文件夹
3. 导入 **预约拨号 v2.0**，放入 **`current.json`**

### 3. 定时预约示例

```bash
python schedule_call.py \
  --to "010-12345678" \
  --call-at "2026-06-08T10:00:00+08:00" \
  --meal-at "2026-06-08T19:00:00+08:00" \
  --title "新桥烧肉订位" \
  --location "王府井银泰in88" \
  --script "你好，我想预订今晚七点，四位，姓张。谢谢。" \
  --airdrop
```

- `--call-at`：何时打电话订位（快捷指令弹窗时间）
- `--meal-at`：何时用餐（写入日历「个人」）
- `--airdrop`：只 AirDrop **`current.json`** 到 iPhone `Shortcuts/` 覆盖

### 4. Pushcut（可选）

```bash
cp phone-call-config.example.json ~/.openclaw/phone-call-config.json
# 填入 pushcut.api_key
python call_popup.py --script "测试" --tel "+8613800138000"
```

## 目录结构

```
phone_call/
├── SKILL.md                 # OpenClaw 技能说明（Agent 读这个）
├── setup.py                 # 首次引导与打包
├── schedule_call.py         # 定时预约
├── dial.py                  # 立即拨打
├── shortcut_builder.py      # 生成 iPhone 快捷指令
├── bundle_transfer.py       # 桌面文件夹 + AirDrop
├── apple_reservation_sync.py # 通讯录 + 日历
├── call_popup.py            # Pushcut 弹窗
├── references/              # 引导与配置文档
├── assets/                  # 快捷指令模板
└── ios/                     # 可选原生弹窗 App
```

## 本机路径（不纳入 git）

| 路径 | 用途 |
|------|------|
| `~/.openclaw/phone-call-setup.json` | 引导进度 |
| `~/.openclaw/phone-call-config.json` | Pushcut 密钥 |
| `~/Desktop/Openclaw-PhoneCall/` | 快捷指令 + `current.json` |
| OpenClaw workspace `memory/phone-calls.json` | 预约队列 |

## 权限

首次使用通讯录 / 日历时，需在 **系统设置 → 隐私与安全性** 中允许终端或 Cursor 访问。

## License

Private / 按需自行补充。
