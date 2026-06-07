# 锁屏 / 前台弹窗（Pushcut）

实现 **台词 + Cancel / Call** 可执行弹窗（锁屏与未锁屏均显示系统通知，带两个操作按钮）。

> iOS 不允许第三方完全自定义「上台词下绿灰按钮」的全屏样式；Pushcut 提供的是 **系统通知 + Cancel/Call 操作钮**，功能等价。若需像素级 UI，见 `ios/OpenClawCallPopup/` 原生 App。

## 一次性配置（约 5 分钟）

### 1. 安装 Pushcut（iPhone）

App Store 搜索 **Pushcut**，安装并登录。

### 2. 创建通知模板「OpenClaw预约」

Pushcut → **Notifications** → **+**

| 字段 | 值 |
|------|-----|
| Name | `OpenClaw预约` |
| Title | `📞 OpenClaw 预约` |
| Text | `（由 API 动态填入台词）` |

**Actions**（顺序重要）：

| 按钮名 | 行为 |
|--------|------|
| `Cancel` | 无操作（关闭通知） |
| `Call` | 留空 — Mac 端 API 会动态传入 `url: tel:+86...` |

开启 **Time Sensitive**（时间敏感，锁屏更显眼）。

### 3. 获取 API Key

Pushcut → **Account** → **Integrations** → **Add API Key**

写入 Mac：

```bash
mkdir -p ~/.openclaw
cp phone-call-config.example.json ~/.openclaw/phone-call-config.json
# 编辑填入 api_key
```

### 4. 测试

```bash
python call_popup.py \
  --script "你好，我想预订今晚六点，四位，姓张。" \
  --tel "+8613800138000"
```

iPhone 应收通知：正文为台词，底部 **Cancel** | **Call**。点 Call 直接拨号。

## 与预约流程集成

`schedule_call.py` 在创建 T-0 提醒后，若配置了 Pushcut，会调用 `call_popup.py`。

到点也可由 **OpenClaw cron** 执行：

```bash
python call_popup.py --script "..." --tel "tel:+86..."
```

## 弹窗设计对照

| 你的设计 | Pushcut 实现 |
|----------|--------------|
| 上半部分台词 | 通知 `text` 正文 |
| 左下 Cancel 灰钮 | 通知操作 `Cancel` |
| 右下 Call 绿钮 | 通知操作 `Call`（系统配色，非自定义绿色） |
| 锁屏可点 | `isTimeSensitive: true` |
| 未锁屏可点 | 通知中心 / 横幅 |
