# iOS 快捷指令说明（实测可用版）

> 推荐：`python setup.py --run` 自动生成；或按下列步骤手搓。

## iPhone 文件路径

在「文件」→ **我的 iPhone（On My iPhone）** 下新建 **`Shortcuts`**，放入 **`current.json`**。

快捷指令读取：目录 `Shortcuts` + 文件 `current.json`（变量名 `current`）。

## 动作顺序

1. **获取文件** — 我的 iPhone / Shortcuts / current.json → `current`
2. **从输入获取词典** — 解析 JSON → 预约数据
3. **获取词典值** — `script`、`tel`
4. **显示提醒** — 弹出台词全文
5. **从菜单选取** — 取消 / 拨打

到点需用户手动运行快捷指令，或在 iOS「自动化」里设「特定时间」触发。

## Mac 侧

桌面 `Openclaw-PhoneCall/` 生成 `current.json`，AirDrop 到 iPhone 的 `Shortcuts/` 覆盖。
