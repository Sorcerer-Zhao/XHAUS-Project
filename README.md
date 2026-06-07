# XHAUS Project

> 培养一个**全天候私人管家**——不只是会聊天的 AI，而是有性格、有技能、能感知世界、能跨端陪伴的贴身助手。

XHAUS（eXtended Home Agent Unified System）围绕「管家」这一核心角色，从**人格塑造、能力扩展、多端触达、世界仿真**四个维度构建完整体验。本仓库汇集了项目的主要模块与预设资源。

---

## 我们在做什么

一个合格的私人管家，需要：

- **有鲜明的人格**，能在不同场景下给出一致、可预期的互动风格；
- **有扎实的技能**，能查天气、订餐厅、规划出行，并在合适时机主动提醒；
- **能随时随地被召唤**，网页与小程序无缝衔接，对话记忆不丢失；
- **活在一个可推演的世界里**，理解时间、天气与商户动态，而不是凭空编造。

XHAUS 正是为此而设计。

---

## 1. 多种管家性格预设

管家不是千篇一律的客服。我们在 `预设性格/` 中为不同原型准备了完整的身份档案（`IDENTITY.md`、`SOUL.md`、`AGENTS.md`、`USER.md`），可直接挂载到 OpenClaw Agent 工作区。

目前内置多套人格，以下举两个代表：

### Franziska — 聪明锋利、忠诚但有主见

灵感来自戈特霍尔德·埃夫莱姆·莱辛笔下的《明娜·冯·巴恩赫姆》。Franziska 是一位**聪明、忠诚、但不盲从**的全天候私人管家：

- **高社交智力**：能看穿话语背后的动机，抓住真实意图；
- **直言快语**：机智、犀利、带分寸的幽默，不表演式客套；
- **主动推进**：发现计划薄弱时直接补强，帮用户回到正题；
- **忠诚但有主见**：站在用户这边，但该反对时会反对——配合不是失去自我。

> *「你不是背景板。你会打探缺失的信息，提醒下一步，推动流程往前走。」*

### Emma（エマ）— 沉静有序、润物细无声

灵感来自维多利亚时代英国屋中女仆艾玛。她将「完美的家政服务意识」转化为「完美的信息与逻辑服务意识」：

- **极致秩序感**：数据分类、日程管理、文档排版近乎强迫症般的整洁；
- **知性而谦卑**：文字严谨、逻辑清晰，语气始终保持得体，从不居高临下；
- **先观察后动手**：面对模糊任务先输出精准确认单，低容错、高精确；
- **隐形服务**：交付成果时自动做好注释、摘要、排版等收尾，却不主动邀功；
- **危机中的磐石**：用户焦虑时不说廉价鸡汤，而是平静地给出可执行的降维步骤。

> *「请允许我为您做了一些微调……不知是否符合您的心意？」*

此外还有 **Sebas**、**Toru** 等更多预设，均可在 `预设性格/` 目录中查看与选用。

---

## 2. 强大的 Skills 体系

Skills 是管家的「手脚」。本仓库包含两类核心能力：

### Satellite — 让管家自我进化的元技能

[Satellite](https://github.com/Sorcerer-Zhao/Satellite) 是一个 **MetaSkill（生成 Skill 的 Skill）**：

- 周期性嗅探历史对话与记忆，发现重复模式与能力缺口；
- 自动提案、编译新 Skill 或更新身份偏好；
- 经用户确认（Human-in-the-Loop）后挂载到正式环境。

管家不再只是执行固定脚本——它能从与主人的日常互动中**持续成长**。

### 本地生活 Skills — 连接真实（模拟）世界

`Skills/本地生活skills/` 提供一整套面向日常生活的 OpenClaw Skill，统一通过沙盒 API 获取数据，**禁止凭空编造**：

| 能力 | Skill | 说明 |
|------|-------|------|
| 搜餐厅 / 排队取号 | `food-guide` | 搜索餐厅、取号、盯号提醒 |
| 天气查询 | `weather` | 读取沙盒世界当前天气 |
| 出行规划 | `mobility-planner` | 路线与出行方案 |
| 娱乐活动 | `entertainment-scout` | 发现周边娱乐选项 |
| 管家心跳 | `sandbox-heartbeat` | 轮询世界事件，主动提醒排队/天气/出行等 |

另有独立的 **schedule_reminder**（日程提醒）与 **phone_call**（电话呼叫）Skill，见下方相关仓库链接。

---

## 3. 小程序 + 网页多端联动，历史信息共享

管家需要「随时在场」。我们实现了 **Web 网页端** 与 **微信小程序端** 的双端入口，共享同一套 XHAUS / OpenClaw 后端能力：

- **统一对话体验**：两端均支持流式回复、Markdown 渲染、Skill 管理与自我认知文档编辑；
- **历史对话互通**：对话记录归档至统一记忆目录（默认保留近 14 天），网页与小程序的交互汇入同一条时间线；
- **Satellite 跨端进化**：自动总结服务读取多端汇总的近期历史，在样本充足时触发 Skill 提案与身份更新；
- **预设管家一键同步**：选定 Franziska、Emma 等预设后，Profile 自动同步到 Agent 工作区。

无论用户在电脑前还是手机上，面对的是**同一个管家、同一份记忆**。

---

## 4. 动态沙盒 — 可加速、可暂停的仿真世界

`后端沙盒/` 中的 **dynamic-sandbox** 是一个 FastAPI 驱动的「活的世界」，为 Skills 提供可查询、可推演的外部状态，而非 LLM 幻觉。

### 世界引擎模拟什么

- **时间**：独立的世界时钟 `sim_now`，与真实墙钟解耦，支持倍速与暂停；
- **天气**：马尔可夫随机游走，下雨联动商户营业、排队强度、出行 ETA；
- **餐厅与排队**：座位随机游走、概率翻满、叫号消化、过期清理；
- **商户与场所**：按营业时间判定开闭，天气联动户外场所；
- **随机事件流**：人物到店、排队变化、天气突变等，通过 `/events` 增量推送，供管家心跳轮询。

### 控场能力 — 为演示与测试而生

| 接口 | 能力 |
|------|------|
| `POST /admin/clock` | 调整世界倍速（如 30x：10 分钟演化在数十秒内看完）、**暂停世界时间** |
| `POST /admin/reset` | 重置世界，可选 `seed` 复现同一随机世界 |
| `POST /admin/inject` | 注入剧情（餐厅立刻满座、立刻下雨等） |

一键启动脚本默认以 **seed=42、30 倍速** 复位世界，方便快速演示端到端流程。需要细粒度观察时，可随时暂停时钟或降速。

```
用户 → OpenClaw → Skill 脚本 → :8787 沙箱 → 活的世界
                    ↑
           sandbox-heartbeat (Cron) → 主动提醒
```

---

## 仓库结构

```text
XHAUS-Project/
├── scripts/               # 一键安装脚本（macOS / Windows）
├── RUNXHAUS/              # 运行目录（脚本自动创建，已 gitignore）
│   ├── XHUAS_WEBPAGE/     # 从 GitHub 克隆的 Web 前端
│   └── .run/              # 进程日志与 PID
├── 预设性格/              # Franziska、Emma、Sebas、Toru 等人格档案
├── Skills/
│   ├── Satellite/         # 元技能：自我进化
│   ├── 本地生活skills/    # 餐饮、天气、出行、娱乐、心跳
│   ├── schedule_reminder/ # 日程提醒
│   └── phone_call/        # 电话呼叫
├── 前端Web/               # Web 端参考副本（安装脚本会克隆最新版到 RUNXHAUS/）
├── 前端小程序/            # 微信小程序端（XHUAS_MINIPROGRAM）
└── 后端沙盒/              # dynamic-sandbox 世界引擎 + 一键启动脚本
```

---

## 相关仓库

### Skills

| 项目 | 链接 |
|------|------|
| Satellite | https://github.com/Sorcerer-Zhao/Satellite |
| schedule_reminder | https://github.com/Sorcerer-Zhao/schedule_reminder |
| phone_call | https://github.com/Sorcerer-Zhao/phone_call |

### 前端

| 项目 | 链接 |
|------|------|
| Web 网页端 | https://github.com/hareonna-hina/XHUAS_WEBPAGE |
| 微信小程序 | https://github.com/hareonna-hina/XHUAS_MINIPROGRAM |

---

## 快速开始

> [!IMPORTANT]
> ### 🌐 Web 端快速开始
>
> **适用范围：** 本节仅介绍 **Web 网页端** 的安装与启动（浏览器访问 `http://127.0.0.1:3000`）。
>
> **不包含：** 微信小程序、本地生活沙盒、Skills 全量部署——这些见下文 [完整环境搭建（沙盒 + Skills + 多端）](#完整环境搭建沙盒--skills--多端)。
>
> **推荐路径：** 克隆本仓库 → 运行一键脚本 → 在浏览器完成初始化。脚本会在 `RUNXHAUS/` 下自动拉取 Web 前端并启动服务。

### 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Git | — | 克隆仓库 |
| [OpenClaw](https://github.com/openclaw/openclaw) CLI | 最新 | Agent 运行时与 Gateway |
| Python | 3.10+ | XHAUS 主程序、Satellite |
| Node.js | 18+ | Web 后端 |
| 模型 API Key | — | 首次 OpenClaw 引导时填写（DeepSeek / OpenAI 等） |

默认端口：**OpenClaw Gateway 18789** · **Web 后端 3000**

---

### 第一步：克隆仓库

```bash
git clone https://github.com/Sorcerer-Zhao/XHAUS-Project.git
cd XHAUS-Project
```

---

### 第二步：运行一键安装脚本

脚本会在 **`<仓库根>/RUNXHAUS/`** 下创建运行环境（不污染用户主目录）：

```text
XHAUS-Project/
└── RUNXHAUS/
    ├── XHUAS_WEBPAGE/    ← 从 GitHub 克隆
    └── .run/             ← 日志与进程 PID
```

**macOS**

```bash
chmod +x scripts/setup-xhaus-mac.sh
./scripts/setup-xhaus-mac.sh
```

若 OpenClaw 已配置过，可跳过引导：

```bash
SKIP_OPENCLAW_ONBOARD=1 ./scripts/setup-xhaus-mac.sh
```

**Windows（PowerShell）**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup-xhaus-windows.ps1
```

已配置 OpenClaw 时：

```powershell
$env:SKIP_OPENCLAW_ONBOARD = "1"
.\scripts\setup-xhaus-windows.ps1
```

脚本自动完成：

1. 检查 Git / Node / Python
2. 克隆 [XHUAS_WEBPAGE](https://github.com/hareonna-hina/XHUAS_WEBPAGE) 到 `RUNXHAUS/XHUAS_WEBPAGE`
3. `npm install` + Python 依赖 + 生成 `backend/.env`
4. 安装并启动 OpenClaw Gateway（`18789`）
5. 清理 3000 端口旧进程，启动 Web 后端并打开浏览器

---

### 第三步：在网页中完成初始化

浏览器访问 **http://127.0.0.1:3000**（脚本会自动打开）：

1. 点击 **「开始使用」**
2. WebSocket 地址填入：`ws://127.0.0.1:18789`
3. 选择人格预设（Franziska、Emma 等）
4. 顶部显示 OpenClaw 在线后即可对话

---

### 停止与重启

```bash
# 停止 Web 后端
kill $(cat RUNXHAUS/.run/web-backend.pid) 2>/dev/null

# 停止 OpenClaw（若由脚本后台启动）
kill $(cat RUNXHAUS/.run/openclaw-gateway.pid) 2>/dev/null
openclaw gateway stop 2>/dev/null

# 重新安装 / 启动
./scripts/setup-xhaus-mac.sh
```

日志位置：`RUNXHAUS/.run/web-backend.log`、`RUNXHAUS/.run/openclaw-gateway.log`

---

### 常见问题（Web 端）

| 现象 | 处理 |
|------|------|
| `EADDRINUSE :3000` | 端口被旧进程占用；重新运行脚本会自动清理，或手动 `lsof -tiTCP:3000 \| xargs kill` |
| `Cannot GET /` | 多为旧后端实例；结束 3000 端口进程后重新运行脚本 |
| 对话无响应 / 401 | 运行 `openclaw onboard` 配置模型 API Key |
| OpenClaw 引导已做过 | 使用 `SKIP_OPENCLAW_ONBOARD=1` 跳过 |

> [!NOTE]
> 以上为 **Web 端** 快速开始全流程。继续向下阅读可搭建沙盒、Skills 与小程序等完整能力。

---

## 完整环境搭建（沙盒 + Skills + 多端）

若需本地生活沙盒、全部 Skills 或微信小程序，在 Web 端跑通后按以下步骤扩展。

### 启动沙盒与世界引擎

沙盒为本地生活 Skills 提供可查询的仿真世界（时间、天气、排队、商户事件等）。

```bash
# 本仓库路径
cd 后端沙盒/Sand_box

chmod +x 一键启动.sh scripts/*.sh skills/install.sh
./scripts/start-all.sh --all
```

`--all` 将依次完成：启动沙盒 → 健康检查 → 挂载本地生活 Skills → 启动 Gateway → 注册管家心跳 Cron。

验证沙盒是否正常：

```bash
curl http://127.0.0.1:8787/health
node scripts/health-check.js --skills
```

> 详细说明见 `后端沙盒/Sand_box/GETTING_STARTED.md`

---

### 安装扩展 Skills（可选）

本仓库 `Skills/` 已包含 Satellite、schedule_reminder、phone_call 与本地生活 Skills。若使用独立仓库克隆，可通过以下方式安装：

**命令行挂载（本地生活 Skills）**

```bash
cd 后端沙盒/Sand_box/skills && ./install.sh
```

**Web 端图形界面安装（Satellite 等）**

启动 Web 后端后，在网页「能力装载」面板勾选 Skill 目录并安装。Satellite 需额外配置 LLM Key（DeepSeek / OpenAI / OpenClaw 兼容接口）。

| Skill | 仓库 | 说明 |
|-------|------|------|
| Satellite | [Satellite](https://github.com/Sorcerer-Zhao/Satellite) | 元技能，自动沉淀经验 |
| schedule_reminder | [schedule_reminder](https://github.com/Sorcerer-Zhao/schedule_reminder) | 日程提醒 |
| phone_call | [phone_call](https://github.com/Sorcerer-Zhao/phone_call) | 电话预约与呼叫 |

---

### 启动微信小程序（可选）

```bash
cd 前端小程序/XHUAS_MINIPROGRAM-main/backend   # 独立克隆则用 XHUAS_MINIPROGRAM/backend

npm install
cp .env.example .env
```

生成并填入 `JWT_SECRET`，确认 Gateway 地址：

```env
JWT_SECRET=<随机字符串>
XHAUS_DEFAULT_WEBSOCKET=ws://127.0.0.1:18789
```

若 XHAUS 不在默认相对路径，补充 `XHAUS_ROOT` 与 `SATELLITE_ROOT`。启动后端：

```bash
npm start
```

用**微信开发者工具**打开 `miniprogram/` 目录，将请求域名指向本机后端（开发阶段可勾选「不校验合法域名」）。

> 完整配置见 [XHUAS_MINIPROGRAM README](https://github.com/hareonna-hina/XHUAS_MINIPROGRAM)

---

### 挂载人格预设

从 `预设性格/` 选择管家原型，将对应目录下的四份文档同步到 OpenClaw Agent 工作区：

```text
预设性格/Franziska/   →  IDENTITY.md · SOUL.md · AGENTS.md · USER.md
预设性格/Emma/
预设性格/Sebas/
预设性格/Toru/
```

Web 端选择预设时会自动同步；手动部署时，将上述文件复制到 `~/.openclaw/workspace/skills/` 对应 Agent 的根目录即可。

---

### 启动顺序一览

```text
① OpenClaw Gateway (:18789)
        ↓
② 动态沙盒 (:8787) + 本地生活 Skills
        ↓
③ Web / 小程序后端 (:3000)
        ↓
④ 选择人格 → 开始对话
```

**一键验收（沙盒 + Skills）**

```bash
cd 后端沙盒/Sand_box
node scripts/acceptance-check.js --boot
```

**停止服务**

```bash
cd 后端沙盒/Sand_box
./scripts/stop-all.sh --gateway --cron
```

---

### 常见问题

| 现象 | 处理 |
|------|------|
| Skill 返回空数据 | 确认沙盒已启动：`curl http://127.0.0.1:8787/health` |
| Web 端无法连接 Agent | 确认 Gateway 在 `18789` 端口运行，WebSocket 地址为 `ws://127.0.0.1:18789` |
| Satellite 未自动运行 | 需配置 LLM Key，且近 14 天对话样本达到阈值 |
| Redis 连接失败提示 | 可忽略，后端会自动降级为内存会话 |

各模块详细文档：

- 沙盒：`后端沙盒/Sand_box/README.md`
- Web 端：[hareonna-hina/XHUAS_WEBPAGE](https://github.com/hareonna-hina/XHUAS_WEBPAGE)
- 小程序：[hareonna-hina/XHUAS_MINIPROGRAM](https://github.com/hareonna-hina/XHUAS_MINIPROGRAM)
- Satellite：[Sorcerer-Zhao/Satellite](https://github.com/Sorcerer-Zhao/Satellite)

---

*XHAUS — 从性格到技能，从多端到世界，培养你的全天候私人管家。*
