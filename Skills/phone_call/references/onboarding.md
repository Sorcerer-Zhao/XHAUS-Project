# Phone-Call 首次引导

Agent 执行 `python setup.py --check-only`，若 `needsOnboarding: true`，**一次只引导一步**，等用户确认后再继续。

步骤名与 `mark-step` 对应关系：

| 步骤名 | 含义 |
|--------|------|
| `mac_bundle` | Mac 桌面已创建 Openclaw-PhoneCall |
| `iphone_shortcuts_folder` | iPhone「我的 iPhone」下已建 `Shortcuts` 文件夹 |
| `iphone_installed` | 快捷指令已导入，且 `current.json` 已放入 `Shortcuts/` |
| `final` | 引导完成 |

---

## Step 1：`mac_bundle`

**Agent 执行：**

```bash
python setup.py --run --skip-airdrop
```

**告诉用户（输出示例）：**

> 先在 Mac 上准备好电话预约文件夹。
>
> **要做什么**：已在桌面创建 `~/Desktop/Openclaw-PhoneCall/`，里面有快捷指令 **预约拨号v2.0**。
>
> **如何验证**：在 Mac 桌面能看到 `Openclaw-PhoneCall` 文件夹。
>
> **完成后请回复**：「Mac 文件夹好了」

**用户确认后：**

```bash
python setup.py --mark-step mac_bundle
```

---

## Step 2：`iphone_shortcuts_folder`

**告诉用户（输出示例）：**

> 接下来在 iPhone 上建一个放数据的文件夹（只需做一次）。
>
> **要做什么**：在 iPhone「文件」App 里，进入 **浏览 → 我的 iPhone（On My iPhone）**，点右上角 **⋯ → 新建文件夹**，命名为 **`Shortcuts`**（注意大小写）。
>
> **如何验证**：在「我的 iPhone」下能看到 `Shortcuts` 空文件夹。
>
> **说明**：快捷指令会从这里读 `current.json`，路径是 **我的 iPhone/Shortcuts/current.json**。
>
> **完成后请回复**：「Shortcuts 文件夹建好了」

**用户确认后：**

```bash
python setup.py --mark-step iphone_shortcuts_folder
```

---

## Step 3：`iphone_installed`

**Agent 执行（可选 AirDrop）：**

```bash
python setup.py --run
# 或已建过文件夹时：python setup.py --airdrop
```

**告诉用户（输出示例）：**

> 现在安装快捷指令并放入数据文件。
>
> **要做什么**：
> 1. Mac AirDrop **`预约拨号v2.0.shortcut`** 到 iPhone → 点 **添加快捷指令**
> 2. 若 Mac 文件夹里有 **`current.json`**（测试用或已有预约），AirDrop 到 iPhone，保存到 **`我的 iPhone/Shortcuts/`** 里（覆盖旧文件）
>
> **如何验证**：
> - 快捷指令 App 里能看到 **预约拨号v2.0**
> - 「文件」→ 我的 iPhone → **Shortcuts** 里有 **current.json**
>
> **完成后请回复**：「快捷指令和数据都好了」

**用户确认后：**

```bash
python setup.py --mark-step iphone_installed
python setup.py --mark-step final
```

---

## 每次预约后（引导完成之后）

Mac 写入 `~/Desktop/Openclaw-PhoneCall/{时间}.json` 并更新 **`current.json`**。

把 Mac 桌面 **`Openclaw-PhoneCall/current.json`** AirDrop 到 iPhone，**覆盖** `我的 iPhone/Shortcuts/current.json`：

```bash
python schedule_call.py ... --airdrop
# 或 python setup.py --airdrop --latest-json
```

到点运行 **预约拨号v2.0** → 弹出台词 → 菜单拨打/取消。
