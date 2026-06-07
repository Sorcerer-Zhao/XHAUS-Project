---
name: satellite
description: Self-evolution MetaSkill that mines the past few days of memory logs to auto-generate reusable Skills and propose identity/preference updates. Use when the user asks to run a self-evolution or "satellite" cycle, extract habits from recent conversations, turn repeated workflows into a new Skill, or review suggested updates to IDENTITY/SOUL/AGENTS/USER.md.
---

# 🛰️ Satellite — 自进化元技能 (MetaSkill)

从最近几天的记忆日志里萃取行为模式，自动生成可复用的 Skill，并提出对身份/认知文件
(`IDENTITY.md` / `SOUL.md` / `AGENTS.md` / `USER.md`) 的合并更新建议，经用户确认后挂载到正式环境。

所有实现代码、测试与文档都在本目录的 `meta_skill/` 子文件夹中。

## 何时使用

- 用户说"跑一次自进化 / satellite 周期"、"从最近对话里提炼习惯"、
  "把我这套重复流程固定成技能"。
- 想看看系统建议如何更新身份/偏好文件。

## 前置条件

- LLM key（默认走 DeepSeek，OpenAI 兼容）。运行前导出其一：
  - `export DEEPSEEK_API_KEY=sk-...`（默认 provider=deepseek，模型 deepseek-v4-pro）
  - 或 `export OPENCLAW_GATEWAY_TOKEN=...` 且 `export SATELLITE_LLM_PROVIDER=openclaw`
- 依赖已装在 `meta_skill/.venv`（`pydantic` / `openai` / `pyyaml`）。

## 怎么用

跑一个完整周期（嗅探 → 研判 → 沙盒生成 → 终端报告 → 等用户确认）：

```bash
cd skills/Satellite/meta_skill
DEEPSEEK_API_KEY=sk-... .venv/bin/python main_satellite.py --hours 72 -v
```

终端会打印「🛰️ 轨道观测报告」，随后等待输入：

- `Y` → 把沙盒技能挪到正式 `skills/`，并按 target 合并身份补丁到 IDENTITY/SOUL/AGENTS/USER.md（写前留 `.bak`），清空沙盒。
- `N` → 清空沙盒，零改动。
- 任意文字 → 当作修改意见回炉重生代码，再次确认。

> 注意：选 `Y` 会真实修改工作区根目录的身份文件（有 `.bak` 可回滚）。
> 想先只看建议不落地，就先选 `N`。

## 常用参数

- `--hours N`：回看窗口（默认 72 小时）。
- `--provider deepseek|openclaw|openai`、`--model <名字>`。
- `--source markdown|sqlite`（默认 markdown，直读工作区 `memory/`）。
- `--identity <路径>`：身份文件位置（默认与 `skills/` 同级的 `IDENTITY.md`）。

## 单阶段 / 运行时网关

```bash
cd skills/Satellite/meta_skill
.venv/bin/python log_sniffer.py --hours 72 --pretty        # 阶段一：导出日志
.venv/bin/python gateway_router.py logs.json               # 阶段二：研判
.venv/bin/python skill_gateway.py list                     # 运行时网关：列技能
.venv/bin/python skill_gateway.py match "提醒我明天开会"     # 触发匹配 + 仲裁
```

## 离线测试（无需 key）

```bash
cd skills/Satellite/meta_skill
for t in log_sniffer gateway_router executor_bridge skill_gateway main_satellite; do .venv/bin/python test_$t.py; done
```

更详细的架构、数据流与限制见 `meta_skill/README.md`。
