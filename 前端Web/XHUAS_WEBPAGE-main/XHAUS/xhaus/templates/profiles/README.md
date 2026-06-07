# Profile 目录说明

每个 Profile 是一个目录，包含四个 Markdown 文档：

| 文件 | 含义 |
|------|------|
| `IDENTITY.md` | 外在身份、称呼、角色边界 |
| `SOUL.md` | 价值观与行为基调 |
| `AGENTS.md` | 运行约束与禁止事项 |
| `USER.md` | 用户偏好与上下文（可编辑） |

## 预设

`presets/` 下为内置角色。每次启动向导时会**自动扫描**该目录：凡包含至少一个 Profile 文档（`IDENTITY.md` 等）的子文件夹都会出现在角色菜单中。

可选 `preset.meta.json` 指定显示名称：

```json
{ "label": "我的角色名", "description": "简短说明" }
```

未提供 meta 时，使用内置中文映射或文件夹名（`my_role` → `my role`）。

## 自定义

复制任一预设到 `~/.xhaus/profiles/<your_name>/` 后修改四个文件，或使用任意目录路径通过 `load_from_directory()` 加载。
