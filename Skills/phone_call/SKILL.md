---
name: phone-call
description: Help the user make phone reservations. Compose spoken Chinese scripts, confirm, dial via user's own phone (Mac+iPhone) or schedule lock-screen reminders. On first use, run setup onboarding. Activate on 打电话订位, 预约通话, 帮我打给, 订位, 预约.
---

# Phone Call Skill（本机拨号 + 预约提醒）

通过 **用户自己的手机号** 完成预约通话：Agent 撰写口语化订位稿 → 用户确认 → 立即拨号或定时提醒 → 用户亲自通话。

**不使用** Twilio / 云外呼。Agent **不代替用户说话**，只提供台词并协助拨号。

---

## ⚠️ 首次使用：必须先做引导（最高优先级）

**每次**处理电话预约请求前，先执行：

```bash
python setup.py --check-only
```

若 JSON 中 `"needsOnboarding": true`：

1. **停止**撰写订位稿、拨号、建提醒等正常流程
2. 阅读并严格遵循 [references/onboarding.md](references/onboarding.md)
3. **逐步引导用户**（一次一步，等用户确认再下一步）
4. 每步完成后按需运行 `python setup.py --mark-step <步骤名>`
5. 直到 `needsOnboarding` 为 `false`，再进入下方正常流程

**引导时的输出要求：**

- 使用 onboarding 文档中的「输出示例」风格，**逐步**说明，禁止一次性贴完整 setup 文档
- 每步说明：**要做什么 → 如何操作 → 如何验证 → 完成后回复什么**
- 用户遇到问题时，只解答当前步骤，不要跳到后面步骤
- 基础设施：`python setup.py --run` → **桌面文件夹** `~/Desktop/Openclaw-PhoneCall` + Finder + AirDrop
- **必须向用户报出桌面文件夹路径**；iPhone 需先建 **我的 iPhone/Shortcuts** 文件夹，再导入快捷指令并放入 `current.json`

引导步骤摘要：Mac 建 Openclaw-PhoneCall → iPhone 建 **我的 iPhone/Shortcuts** 文件夹 → 导入快捷指令 + 放入 current.json → 完成。详见 [references/onboarding.md](references/onboarding.md)。

`check-only` 返回的 `onboardingStep` 决定当前应引导哪一步；每步完成后 `python setup.py --mark-step <步骤名>`。

---

## Prerequisites（引导完成后应满足）

1. **iPhone + Mac** 同一 Apple ID（立即拨号可用 `dial.py`）
2. 桌面存在 **`~/Desktop/Openclaw-PhoneCall/`**（快捷指令 + 按时间命名的 json）
3. iPhone 路径：**我的 iPhone/Shortcuts/current.json**（Mac 生成后 AirDrop 覆盖）
4. **不写提醒事项/日历**；到点运行快捷指令弹窗

`python setup.py --run` → 创建 Openclaw-PhoneCall 文件夹 + AirDrop  
`python setup.py --airdrop --latest-json` → AirDrop **current.json**（队首待办）

---

## When to Activate

- 打电话订餐厅 / 预约 / 挂号
- 「帮我打给 XXX 说 YYY」
- 「明天上午 10 点打给餐厅订位」

**Do NOT activate** for: 紧急号码、骚扰、用户明确只需在线订座。

---

## Workflow Overview

```
检查 setup.py --check-only
    → [首次] 逐步引导 onboarding
用户提出预约
    → 1. 撰写口语化订位稿
    → 2. 确认（号码 / 时间 / 台词）
    → 3a. 立即 dial.py     或    3b. 定时 schedule_call.py
```

---

## Phase 1: 撰写订位稿

生成 **简短、自然** 的中文口语稿。

**必须包含**（按场景）：目的、时间、人数、姓名、特殊要求、礼貌结尾。  
**禁止**：emoji、markdown、书面长句。

先展示全文。**不要**在用户确认前拨号或建提醒。

---

## Phase 2: 确认

确认：被叫号码、**打电话时间**（`call-at`）、**用餐时间**（`meal-at`）、地点（如有）、订位稿全文。  
用户说「直接打」时可跳过二次确认，但仍展示台词。

---

## Phase 3a: 立即拨打

```bash
python dial.py --to <phone> [--dry-run]
```

成功后：告知已在 Mac 发起拨号，附上建议台词。  
仅 iPhone：引导运行 **OpenClaw 预约拨号** 或点号码。

---

## Phase 3b: 定时预约

```bash
python schedule_call.py \
  --to <phone> \
  --call-at "2026-06-07T10:00:00+08:00" \
  --meal-at "2026-06-07T19:00:00+08:00" \
  --title "新桥烧肉订位" \
  --location "王府井银泰in88" \
  --script "你好，我想预订明天晚上六点，四位，姓张。谢谢。"
```

用户确认预约后，`schedule_call.py` 会同时：
- 将 **手机号** 存入 Mac **通讯录**（商户名 = `--title`）
- 将 **用餐时间** 写入 iCloud **日历「个人」**（`--meal-at`，同步到 iPhone）
- 写入 `~/Desktop/Openclaw-PhoneCall/` 的 json 并更新 **`current.json`**

`--call-at` = 何时打电话订位；`--meal-at` = 何时去吃饭（日历事件）。两者通常不同。  
可选 `--airdrop`：只 AirDrop **`current.json`** 到 iPhone `我的 iPhone/Shortcuts/` 覆盖。  
若通讯录/日历权限未开，告知用户在「系统设置 → 隐私」中授权终端。

### 到点弹窗

告知用户：AirDrop **`current.json`** 覆盖 iPhone `Shortcuts/`；到点运行 **「预约拨号v2.0」** 弹出台词 → 选「拨打」或「取消」。  
**不要**让用户去找时间戳 json 文件。

---

## 查询与取消

- 读取 `memory/phone-calls.json` 列出 `scheduled` 条目
- 取消：删条目、删除或标记对应 json

---

## Setup 命令参考

| 命令 | 用途 |
|------|------|
| `python setup.py --check-only` | 是否需首次引导 |
| `python setup.py --run` | 创建 Openclaw-PhoneCall + AirDrop 到 iPhone |
| `python setup.py --airdrop` | AirDrop 更新后的 json |
| `python setup.py --mark-step <name>` | 标记引导步骤完成 |
| `schedule_call.py ... --airdrop` | 预约后 AirDrop json |

---

## File Locations

| 路径 | 用途 |
|------|------|
| `~/.openclaw/phone-call-setup.json` | 首次引导进度 |
| `memory/phone-calls.json` | 预约任务队列 |
| `~/Desktop/Openclaw-PhoneCall/` | 快捷指令 + 按时间命名的预约 json |
| `{YYYY-MM-DD_HH-MM-SS}.json` | `completed: false` 待办；快捷指令完成后改为 `true` |

---

## Safety

- 禁止紧急号码、骚扰
- 默认确认台词；不代替用户通话
