# OpenClaw Call Popup（可选原生 App）

实现你描述的弹窗 UI：

```
┌─────────────────────────┐
│  台词（上半部分）         │
├────────────┬────────────┤
│  Cancel    │    Call    │
│  (灰圆角)  │  (绿圆角)  │
└────────────┴────────────┘
```

## 与 Skill 的关系

- **默认方案**：Pushcut 通知（锁屏 + 未锁屏均可点 Cancel/Call）— 见 `references/pushcut-popup-setup.md`
- **本 App**：需要完全自定义绿/灰按钮时，用 Xcode 编译安装到 iPhone

## 使用

1. 在 Xcode 新建 iOS App，把 `CallPopupView.swift` 加入工程
2. 注册 URL Scheme：`openclawcall`
3. Pushcut「Call」按钮 URL 设为：`openclawcall://popup?script=...&tel=tel:+86...`
4. App 打开后全屏展示 `CallPopupView`，Call 调起系统拨号

## 限制

iOS **不允许**第三方在锁屏上绘制完全自定义全屏弹窗（类似来电界面）。锁屏场景请用 Pushcut 时间敏感通知。
