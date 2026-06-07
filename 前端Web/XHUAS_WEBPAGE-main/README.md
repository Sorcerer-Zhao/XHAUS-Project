# XHUAS_WEBPAGE

OpenClaw / XHAUS 的网页前端与本地后端控制台。它提供一个统一的网页入口，用来激活 XHAUS、连接 OpenClaw Gateway、与当前 Agent 对话、安装本地 Skill、保存自我认知文档，并通过 Satellite 自动整理近两周对话历史。

本仓库是初始化发布包，不包含任何个人运行数据：

- 不包含 `backend/node_modules`
- 不包含 `backend/.env`
- 不包含 `XHAUS/runtime`
- 不包含聊天历史、自我认知文档、Satellite 报告
- 不包含用户本机的 `~/.openclaw` 或 `~/.xhaus` 数据

## 目录结构

```text
XHUAS_WEBPAGE/
  backend/                 # Node.js 后端 + 网页静态文件
    public/                # 网页 UI、样式、logo、Markdown 渲染
    src/                   # API、OpenClaw/XHAUS/Satellite 连接逻辑
    .env.example           # 环境变量模板
    package.json
  XHAUS/                   # XHAUS 主程序与本地 Skill 安装工具
  Satellite/               # 自动总结与自进化 MetaSkill
  examples/
    test-skill-plain/      # 最小 Skill 示例，只有 SKILL.md
```

## 前置要求

1. Node.js 18 或更高版本
2. Python 3.10 或更高版本
3. OpenClaw 已安装，并且本地 Gateway 可以运行
4. 如果要使用 Satellite 自动总结，需要配置 DeepSeek / OpenAI / OpenClaw 兼容 LLM Key

Redis 不是必须的。未安装 Redis 时，后端会自动使用内存会话，开发测试可以直接跑。

## 安装依赖

Windows PowerShell：

```powershell
cd backend
npm install
```

安装 XHAUS / Satellite Python 依赖：

```powershell
cd ..\XHAUS
python -m pip install -r requirements.txt

cd ..\Satellite\meta_skill
python -m pip install -r requirements.txt
```

macOS / Linux 终端：

```bash
cd backend
npm install

cd ../XHAUS
python3 -m pip install -r requirements.txt

cd ../Satellite/meta_skill
python3 -m pip install -r requirements.txt
```

## 配置环境变量

后端启动前需要有一个 `backend\.env` 文件。这个文件只保存在使用者本机，用来放端口、密钥、Python 路径等配置；不要把 `.env` 上传到 GitHub。

Windows PowerShell：如果你当前在 `XHUAS_WEBPAGE` 根目录，按下面步骤操作：

```powershell
cd backend
copy .env.example .env
notepad .env
```

如果你当前还在别的目录，也可以直接这样进入：

```powershell
cd C:\你的路径\XHUAS_WEBPAGE\backend
copy .env.example .env
notepad .env
```

macOS / Linux 终端：如果你当前在 `XHUAS_WEBPAGE` 根目录，按下面步骤操作：

```bash
cd backend
cp .env.example .env
nano .env
```

如果你想用系统自带的文本编辑器，也可以：

```bash
open -e .env
```

执行 `notepad .env` 后会打开记事本。至少把这一行改掉：

```env
JWT_SECRET=please-change-this-to-a-random-string
```

建议改成一串只有你本机知道的随机字符，例如：

```env
JWT_SECRET=xhuas-local-2026-change-this-to-your-own-random-string
```

`JWT_SECRET` 只是本地网页后端签发会话用的密钥，不需要去任何网站申请。随便写一段足够长、别人猜不到的字符串即可。

`.env` 中常用配置如下：

```env
PORT=3000
OPENCLAW_CHAT_COMPLETIONS_URL=http://127.0.0.1:18789/v1/chat/completions
OPENCLAW_GATEWAY_URL=
OPENCLAW_GATEWAY_TOKEN=
XHUAS_PROJECT_ROOT=
XHAUS_PYTHON=
```

通常第一次测试时只需要改 `JWT_SECRET`。`PORT=3000` 可以保持不变，网页地址就是 `http://127.0.0.1:3000`。

`XHUAS_PROJECT_ROOT` 默认可以留空。后端会从自身目录向上查找 `XHAUS/main.py`，只要目录结构保持为下面这样，就能自动找到：

```text
XHUAS_WEBPAGE/
  backend/
  XHAUS/
  Satellite/
```

如果你把 `backend`、`XHAUS`、`Satellite` 分开移动了，才需要手动填写 `XHUAS_PROJECT_ROOT`，值是包含这三个目录的 `XHUAS_WEBPAGE` 绝对路径，例如：

```env
XHUAS_PROJECT_ROOT=C:\Users\你的用户名\Desktop\XHUAS_WEBPAGE
```

macOS / Linux 示例：

```env
XHUAS_PROJECT_ROOT=/Users/你的用户名/Desktop/XHUAS_WEBPAGE
```

如果 `python` 命令不是你想用的 Python，可以设置：

```env
XHAUS_PYTHON=C:\Path\To\python.exe
```

例如你的 Python 在 Anaconda 里，可以写成类似：

```env
XHAUS_PYTHON=D:\Anaconda22\python.exe
```

macOS 上可以先查看 Python 路径：

```bash
which python3
```

然后写成类似：

```env
XHAUS_PYTHON=/opt/homebrew/bin/python3
```

Satellite 自动总结可选配置：

```env
DEEPSEEK_API_KEY=你的 DeepSeek Key
```

或者使用 OpenAI：

```env
SATELLITE_LLM_PROVIDER=openai
SATELLITE_LLM_API_KEY=你的 OpenAI Key
SATELLITE_LLM_MODEL=gpt-4o-mini
```

或者使用 OpenClaw Gateway 的兼容接口：

```env
SATELLITE_LLM_PROVIDER=openclaw
OPENCLAW_GATEWAY_TOKEN=你的 Gateway Token
```

改完后在记事本里按 `Ctrl+S` 保存，然后关闭记事本。回到 PowerShell，确认还在 `backend` 目录，再执行：

```powershell
npm start
```

## 启动

Windows PowerShell：在 `backend` 目录启动：

```powershell
npm start
```

macOS / Linux 终端同样在 `backend` 目录启动：

```bash
npm start
```

看到类似输出即表示后端已启动：

```text
server_listening_on_3000
```

然后打开：

```text
http://127.0.0.1:3000
```

## 首次使用流程

1. 打开网页，进入开始界面。
2. 点击“开始使用”。
3. 右侧 Runtime 会自动执行 `XHAUS/main.py`。
4. XHAUS 初始化会提示输入 OpenClaw WebSocket 地址，例如：

   ```text
   ws://127.0.0.1:18789
   ```

5. 输入后点击发送。
6. 选择人设，例如默认管家、优雅女仆、Emma 等。
7. 页面顶部显示 OpenClaw 在线后，即可在左侧对话框聊天。

WebSocket 地址会记忆在浏览器本地缓存里。第二次启动时，WebSocket 输入阶段会显示历史地址按钮。

如果选择“自定义角色”，XHAUS 会依次打开 `IDENTITY.md`、`SOUL.md`、`AGENTS.md`、`USER.md` 等文件让你编辑：

- Windows 会打开记事本。每编辑完一个文件，都要按 `Ctrl+S` 保存，再关闭记事本窗口，XHAUS 才会继续下一步。
- macOS 会打开 TextEdit。每编辑完一个文件，都要按 `Command+S` 保存，再关闭 TextEdit 文档窗口，XHAUS 才会继续下一步。
- Linux 会使用系统可用的编辑器；保存后关闭编辑器窗口或退出终端编辑器即可继续。

如果忘记保存就关闭，XHAUS 会继续执行，但你刚才写的人设内容不会生效。

## 功能说明

### 1. 对话窗口

左侧是主对话区。网页会把用户消息发送到当前 XHAUS Agent，并把 OpenClaw 回复渲染回来。

Agent 回复支持基础 Markdown 渲染：

- 标题：`#` / `##` / `###`
- 加粗：`**text**`
- 斜体：`*text*`
- 列表：`- item`
- 表格
- 分隔线：`---`

用户消息保持纯文本渲染，避免用户输入被误当作 HTML。

### 2. Runtime / 连接 XHAUS

右侧 Runtime 区用于：

- 激活 XHAUS
- 停止 XHAUS
- 输入初始化过程中的 WebSocket、Agent 名称、人设编号等
- 查看 `main.py` 输出日志

日志窗口内部可滚动。点击“放大”会在页面中央打开大窗口查看完整日志。

### 3. 能力装载 / Skill 安装

在“能力装载”中输入一个本地 Skill 文件夹路径，点击“添加 Skill”。

Skill 文件夹至少需要：

```text
my-skill/
  SKILL.md
```

示例 Skill：

```text
examples/test-skill-plain
```

可以直接测试：

```text
XHUAS_WEBPAGE\examples\test-skill-plain
```

安装逻辑：

1. 复制本地 Skill 到 `~/.xhaus/skills/<skill-name>`
2. 同步到每个 OpenClaw Agent workspace
3. 重启 OpenClaw Gateway

Windows 普通权限通常不能创建符号链接。项目已做兼容：符号链接失败时会自动复制 Skill 到 workspace，所以不需要管理员权限。

如果同名 Skill 已存在，勾选“覆盖”后再安装。

### 4. 自我认知文档

“自我认知文档”用于保存用户偏好、长期目标、节奏习惯等。

文档会保存到：

```text
XHAUS/runtime/self_cognition
```

同标题内容会追加到同一个 Markdown 文件中。

聊天时，后端会读取这些文档，并注入到 Agent 的系统上下文里，让回复参考用户偏好。

### 5. Satellite 自动进化

Satellite 会保存近两周对话历史，并尝试总结出新的偏好、认知建议或可复用 Skill。

历史保存位置：

```text
XHAUS/runtime/satellite_memory
```

默认只保留近 14 天。

Satellite 报告保存位置：

```text
XHAUS/runtime/self_cognition/Satellite-自动进化报告.md
```

网页中可以点击“立即运行”手动触发。自动运行默认每 6 小时尝试一次，并且需要足够的近期对话样本。

Satellite 需要 LLM Key。如果没有 Key，它会保存历史，但不会生成总结报告。

## 测试方法

### 1. 静态检查

在项目根目录执行：

```powershell
node --check backend\public\app.js
node --check backend\src\server.js
node --check backend\src\routes\xhaus.js
node --check backend\src\routes\chat.js
node --check backend\src\services\openclawClient.js
node --check backend\src\services\satelliteService.js
python -m py_compile XHAUS\main.py XHAUS\install_skill.py XHAUS\frontend_chat_bridge.py
```

### 2. 启动检查

```powershell
cd backend
npm start
```

打开：

```text
http://127.0.0.1:3000
```

检查：

- 开始界面能显示 logo
- 点击“开始使用”进入主界面
- Runtime 区能显示 XHAUS 初始化日志
- “放大”按钮能打开居中弹窗
- 对话区 Agent 回复能渲染标题、加粗、列表、表格、分隔线

### 3. Skill 安装测试

在网页“能力装载”输入：

```text
<你的项目路径>\examples\test-skill-plain
```

点击“添加 Skill”。

成功后应看到：

```text
OK 已安装到共享目录
```

并且可以在本机看到：

```text
%USERPROFILE%\.xhaus\skills\test-skill-plain
```

### 4. 自我认知测试

在“自我认知文档”输入：

```text
标题：我的偏好与节奏
内容：我喜欢详细的日程安排。
```

点击“添加文档”。

确认生成：

```text
XHAUS/runtime/self_cognition/我的偏好与节奏.md
```

然后问 Agent：

```text
你知道我喜欢什么样的日程安排吗？
```

Agent 应该能参考该文档回答。

### 5. Satellite 测试

先确保 `.env` 中配置了可用 Key，例如：

```env
DEEPSEEK_API_KEY=你的key
```

进行几轮聊天后，点击“Satellite 自动进化”的“立即运行”。

成功后检查：

```text
XHAUS/runtime/self_cognition/Satellite-自动进化报告.md
```

## 常见问题

### 启动时报 Missing required env: JWT_SECRET

复制 `.env.example` 为 `.env`，并填写：

```env
JWT_SECRET=任意随机长字符串
```

### XHAUS 找不到 main.py

请确认目录结构仍然是：

```text
XHUAS_WEBPAGE/
  backend/
  XHAUS/
```

如果你移动了目录，可以设置：

```env
XHUAS_PROJECT_ROOT=你的 XHUAS_WEBPAGE 绝对路径
```

### Windows 提示没有符号链接权限

这是正常的。项目会自动 fallback 为复制 Skill 到 workspace，不需要管理员权限。

### Satellite 没有生成报告

通常是没有配置 LLM Key，或者历史样本太少。查看：

```text
XHAUS/runtime/satellite/state.json
```

其中 `last_stdout` / `last_stderr` 会说明失败原因。

### OpenClaw 连不上

确认 OpenClaw Gateway 已启动，并在 XHAUS 初始化时输入正确 WebSocket，例如：

```text
ws://127.0.0.1:18789
```

不同机器的 Gateway 地址可能不同，第一次需要手动输入。
