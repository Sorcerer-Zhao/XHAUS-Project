# XHUAS 微信小程序

这是 OpenClaw XHAUS 的微信小程序前端和本地 Node.js 后端网关。它提供：

- 温暖风格的小程序聊天界面
- OpenClaw 回复流式输出
- Markdown 渲染：标题、加粗、分隔线、列表、表格、代码块
- 独立历史对话
- 自我认知文档管理
- Skill 安装、查看、编辑、删除
- Satellite 自动进化状态与报告
- 预设管家与自定义管家人设

这个目录已经整理成适合上传 GitHub 的初始化版本，不包含本地运行数据、`.env`、`node_modules`、个人 OpenClaw workspace、自我认知文档、自定义人设或微信私有配置。

## 1. 目录结构

```text
XHUAS_MINIPROGRAMM/
  backend/              本地 Node.js 后端网关
  miniprogram/          微信小程序前端
  cloudfunctions/       原始云函数脚手架
  project.config.json   安全的小程序项目模板配置
```

后端需要在同一台电脑上访问 XHAUS。Satellite 是可选功能。

推荐目录结构：

```text
你的工作目录/
  XHAUS/
  Satellite/            可选，用于 Satellite 自动进化
  XHUAS_MINIPROGRAMM/
```

如果你的 XHAUS 或 Satellite 放在其他位置，可以在 `backend/.env` 里设置 `XHAUS_ROOT` 和 `SATELLITE_ROOT`。

## 2. 运行要求

- Node.js 18 或更高版本
- Python 3.10 或更高版本
- 微信开发者工具
- 本地可用的 OpenClaw Gateway
- XHAUS 源码目录，里面需要有 `main.py`
- 可选：Redis。不启动 Redis 也可以，后端会自动使用内存 fallback。
- 可选：Satellite 目录和 LLM API Key，用于自动总结与进化。

## 3. 后端配置

进入后端目录：

```text
XHUAS_MINIPROGRAMM/backend
```

### Windows PowerShell

```powershell
cd 路径\到\XHUAS_MINIPROGRAMM\backend
npm install
Copy-Item .env.example .env
notepad .env
```

生成 `JWT_SECRET`：

```powershell
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

把输出的随机字符串填进 `.env`：

```env
JWT_SECRET=你刚才生成的随机字符串
```

如果 XHAUS 不在 `XHUAS_MINIPROGRAMM` 的同级目录，填写：

```env
XHAUS_ROOT=C:\你的路径\XHAUS
```

如果系统找不到 Python，填写：

```env
XHAUS_PYTHON=C:\你的路径\python.exe
```

如果 Satellite 不在 `XHUAS_MINIPROGRAMM` 的同级目录，填写：

```env
SATELLITE_ROOT=C:\你的路径\Satellite
```

启动后端：

```powershell
npm start
```

看到下面这行就说明后端启动成功：

```text
server_listening_on_3000
```

如果看到：

```text
redis_fallback_memory connect ECONNREFUSED 127.0.0.1:6379
```

这是正常的。它表示没有连接 Redis，后端会用内存模式继续运行。

### macOS / Linux

```bash
cd /路径/到/XHUAS_MINIPROGRAMM/backend
npm install
cp .env.example .env
open -e .env
```

如果 `open -e` 不可用，可以用：

```bash
nano .env
```

生成 `JWT_SECRET`：

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

把输出的随机字符串填进 `.env`：

```env
JWT_SECRET=你刚才生成的随机字符串
```

如果 XHAUS 不在 `XHUAS_MINIPROGRAMM` 的同级目录，填写：

```env
XHAUS_ROOT=/Users/你的用户名/路径/XHAUS
```

如果系统找不到 Python，填写：

```env
XHAUS_PYTHON=/你的路径/python3
```

如果 Satellite 不在 `XHUAS_MINIPROGRAMM` 的同级目录，填写：

```env
SATELLITE_ROOT=/Users/你的用户名/路径/Satellite
```

启动后端：

```bash
npm start
```

## 4. `.env` 主要配置项

必须填写：

```env
JWT_SECRET=换成一段足够长的随机字符串
```

通常需要确认：

```env
XHAUS_ROOT=
XHAUS_DEFAULT_WEBSOCKET=ws://127.0.0.1:18789
XHAUS_PYTHON=
```

Satellite 相关：

```env
SATELLITE_ROOT=
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
SATELLITE_LLM_PROVIDER=
```

微信登录正式接入时使用：

```env
WECHAT_APPID=
WECHAT_APP_SECRET=
```

如果只是本地模拟器测试，`WECHAT_APPID` 和 `WECHAT_APP_SECRET` 可以先留空。

## 5. 微信小程序配置

1. 安装微信开发者工具。
2. 打开微信开发者工具。
3. 选择“导入项目”。
4. 选择 `XHUAS_MINIPROGRAMM` 这个文件夹。
5. 本地测试可以使用模板里的 `touristappid`。
6. 如果你有自己的小程序 AppID，可以在微信开发者工具的项目设置里替换。

### 后端地址配置

小程序前端读取后端地址的位置：

```text
miniprogram/envList.js
```

默认本地模拟器配置：

```js
apiBase: "http://127.0.0.1:3000"
```

如果只在微信开发者工具模拟器里测试，通常不用改。

如果用真机调试，`127.0.0.1` 指的是手机自己，不是电脑。需要改成电脑的局域网 IP：

```js
apiBase: "http://192.168.x.x:3000"
```

同时确保手机和电脑在同一个网络里，并且电脑防火墙允许 Node.js 使用 `3000` 端口。

如果要发布体验版或正式版，微信要求合法 HTTPS 域名。需要把后端部署到服务器，或者给本地后端加 HTTPS 反向代理/隧道，然后把 `apiBase` 改成：

```js
apiBase: "https://api.your-domain.com"
```

本地开发时，如果请求被域名校验拦住，可以在微信开发者工具里勾选：

```text
不校验合法域名、web-view 域名、TLS 版本以及 HTTPS 证书
```

## 6. OpenClaw / XHAUS 使用流程

1. 在电脑上启动 OpenClaw Gateway。
2. 在 `backend` 目录运行 `npm start`。
3. 在微信开发者工具里打开小程序。
4. 第一次聊天时，根据提示输入 WebSocket 地址。
5. 小程序会在本地保存 WebSocket 历史，下次可以从列表选择。
6. 点击“换管家”可以选择预设管家或自定义管家。

每个使用者都应该填写自己正在运行的 OpenClaw Gateway WebSocket。也就是说，同学在自己的电脑上测试时，填的是同学电脑上的 Gateway 地址，不需要也不应该填别人的地址。

默认 WebSocket：

```text
ws://127.0.0.1:18789
```

真机调试时要使用电脑局域网 IP：

```text
ws://192.168.x.x:18789
```

## 7. 功能说明

### 聊天

- 每个对话都是独立会话。
- OpenClaw 回复会流式显示。
- 支持 Markdown 标题、加粗、分隔线、列表、表格和代码块。
- 底部有餐饮、娱乐、出行、日程快捷入口。

### 历史

- 点击“历史”查看过往对话。
- 可以切换不同对话。
- 可以编辑对话名称，方便管理。

### Skill

- 点击“Skill”查看本地 Skill。
- 添加 Skill 时选择或输入本地 Skill 文件夹路径。
- 有效 Skill 通常需要包含 `SKILL.md`。
- 可以查看、编辑和删除 Skill。
- Skill 变更后，后端会同步到 OpenClaw workspace，并在需要时重启 Gateway。

### 记忆

- 点击“记忆”管理自我认知文档。
- 可以保存偏好、习惯、日程风格和长期目标。
- 文档会存到 XHAUS 的 runtime 自我认知目录。
- 点击文档可以查看 Markdown 渲染后的内容。
- 可以编辑或删除文档。

### Satellite

- Satellite 会读取最近一段时间的历史对话。
- 默认保留最近 14 天历史。
- 在“记忆”页点击“运行”可以手动触发 Satellite。
- 生成的报告会显示在记忆文档列表里。
- 如果 Satellite 需要外部模型，请配置 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`。

### 自定义管家

- 点击“换管家”，再点击“自定义”。
- 可以编辑以下文件：
  - `IDENTITY.md`：管家是谁、身份与边界
  - `SOUL.md`：语气、性格和陪伴方式
  - `AGENTS.md`：多 Agent 分工协作方式
  - `USER.md`：默认了解的用户偏好
- 保存时需要给新管家取名。
- 后端会自动加入身份锚点，避免新角色错误继承 Emma、Franziska 或其他预设人设。
- 自定义管家可以删除；系统预设管家不能删除。

## 8. 数据与隐私

这个 GitHub 包不包含任何用户数据。

运行后，每个用户自己的数据会生成在本机：

- `backend/.env`：后端密钥和本地路径
- `~/.xhaus/skills`：共享 Skill
- `~/.xhaus/profiles`：自定义管家人设
- `~/.openclaw/workspace*`：OpenClaw workspace
- `XHAUS/runtime/self_cognition`：自我认知文档和 Satellite 报告
- `XHAUS/runtime/satellite_memory`：Satellite 使用的历史对话

不要提交 `.env`、运行目录、OpenClaw workspace、API Key 或个人记忆文件。

## 9. 测试清单

后端测试：

```bash
cd backend
npm install
npm start
```

期望看到：

```text
server_listening_on_3000
```

健康检查：

```bash
curl http://127.0.0.1:3000/api/status
```

小程序测试：

1. 在微信开发者工具导入 `XHUAS_MINIPROGRAMM`。
2. 点击“编译”。
3. 确认首页聊天界面可以打开。
4. 发送“你是谁”。
5. 如果提示 WebSocket，输入本机 OpenClaw Gateway 地址。
6. 确认回复会流式显示到聊天窗口。
7. 新建一个对话，确认旧对话出现在“历史”里。
8. 添加一条自我认知文档，重新打开“记忆”确认还在。
9. 打开 Skill 页面，确认可以查看或添加 Skill。
10. 创建一个自定义管家，切换过去后问“你是谁”。
11. 删除这个自定义管家，确认它从选择列表消失。

真机测试：

1. 把 `miniprogram/envList.js` 里的 develop `apiBase` 改成电脑局域网 IP。
2. WebSocket 使用类似 `ws://192.168.x.x:18789` 的地址。
3. 保持电脑上的 backend、XHAUS、OpenClaw Gateway 都在运行。
4. 确认防火墙允许 `3000` 和 `18789` 端口。

## 10. 常见问题

### 提示缺少 `JWT_SECRET`

说明还没有创建或填写 `backend/.env`。从 `.env.example` 复制一份 `.env`，然后填写 `JWT_SECRET`。

### 真机连不上后端

真机上不能用 `127.0.0.1` 访问电脑。把 `miniprogram/envList.js` 的 `apiBase` 改成电脑局域网 IP。

### 出现 `xhaus_main_not_found`

在 `backend/.env` 里设置 `XHAUS_ROOT`，指向包含 `main.py` 的 XHAUS 目录。

### 找不到 Python

在 `backend/.env` 里设置 `XHAUS_PYTHON`。

### Satellite 运行失败

检查 `SATELLITE_ROOT` 是否正确；如果 Satellite 需要外部模型，检查 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`。

### Redis 报错

本地测试可以忽略 Redis 报错。没有 Redis 时，后端会自动使用内存 fallback。
