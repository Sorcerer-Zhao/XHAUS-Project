# 🛰️ Satellite — MetaSkill（生成 Skill 的 Skill）

> 让管家具备自我进化能力的元技能：从重复的问答循环中自动萃取模式，
> 形成可复用的 Skill 或身份偏好，经用户确认后挂载到正式环境。

Satellite 是一个**双层、四阶段**的流水线。网关层（策略大脑）周期性嗅探历史对话、
研判行为模式；执行层（生成手脚）把决策编译成沙盒里的真实技能，再由用户拍板挂载。

---

## 架构总览

```
  Markdown    ┌────────────────────────── 网关层 (策略大脑) ──────────────────────────┐
  记忆日志    │  阶段一 嗅探         阶段二 研判 (+现有技能清单去重)                    │
 memory/ ───▶│  log_sniffer  ──▶  gateway_router.evaluate_habits ──▶ GatewayDecision  │
 (默认源)    │                         ▲ build_skill_catalog (skill_gateway)          │
            └─────────────────────────┴────────────────────────────────┬─────────────┘
                                                                        │ JSON 决策
            ┌─────────────────────────── 执行层 (生成手脚) ─────────────▼─────────────┐
            │  阶段三 编译                         阶段四 推送 + 挂载                   │
            │  executor_bridge                     main_satellite                      │
            │  ├─ init_skill.py  (脚手架)          ├─ 终端报告 + Human-in-the-Loop      │
            │  ├─ LLM/SkillCompiler (executor.py)  ├─ [Y] 挂载 skills/ + 并入 4 身份文件 │
            │  └─ 质检: quick_validate + 编译检测  ├─ [N] 清空沙盒                       │
            │      ▼  (失败自愈重生一次)           └─ [其他] 回炉重构再确认             │
            │  .staging_skills/{name}/                                                  │
            └───────────────────────────────────────────────────────────────────────┘
```

---

## 模块清单

| 文件 | 阶段 | 角色 | 关键 API |
|------|------|------|----------|
| `meta_skill_plan.md` | — | 全局规划与 SOP | — |
| `log_sniffer.py` | 一 | **直读 Markdown 记忆**(默认) / 可选 SQLite，清洗近 N 小时日志 | `sniff()`, `fetch_recent_logs()`, `fetch_recent_logs_markdown()` |
| `gateway_router.py` | 二 | LLM 策略研判(去重/复杂度过滤 + 补丁文件路由)，严格校验决策 | `evaluate_habits()`, `GatewayDecision`, `FilePatch`, `make_llm_client()` |
| `executor_bridge.py` | 三 | 脚手架 + LLM 代码生成 + 原厂质检 + **编译检测/自愈** | `generate_skill_to_staging()`, `stage_identity_update()`, `normalize_patches()` |
| `skill_gateway.py` | 运行时 | **运行时网关**：发现/触发匹配/优先级仲裁/热加载卸载/调用 + 去重清单 | `SkillGateway`, `build_skill_catalog()` |
| `main_satellite.py` | 四 | 串联全流程 + 人机确认 + 挂载 + **多文件身份合并** | `run_satellite_cycle()`, `_apply_identity_updates()` |
| `test_*.py` | — | 各模块离线 mock 验收 (5 套) | — |

---

## 数据流（逐阶段）

1. **嗅探** `log_sniffer.sniff(hours=72)` 只读打开 SQLite，抓取窗口内记录，
   清洗为统一结构并紧凑序列化：

   ```json
   [{"timestamp":"…","user_intent":"…","tools_used":[{"name":"…","args":{}}],"assistant_response":"…"}]
   ```

2. **研判** `gateway_router.evaluate_habits(logs_json)` 用一段三维度 System Prompt
   （工具行为层 / 认知偏好层 / 显式指令层，后者最高优先级）让 LLM 产出并强制
   Pydantic 校验的 `GatewayDecision`：

   ```json
   {
     "skill_generation": {"action":"merge|upgrade|ignore","target_name":"…","description":"…","compile_instruction":"…"},
     "identity_update":   {"action":"update|ignore","patches":[{"target":"USER.md","content":"…"}]}
   }
   ```

   每条 patch 带 `target` 文件路由（见「身份/认知文件路由」）。纯字符串 patch 向后兼容，
   自动归到 `IDENTITY.md`。解析/校验失败会把错误回喂模型重试（默认 3 次）。

3. **编译** `executor_bridge.generate_skill_to_staging(target_name, compile_instruction)`：
   - 步骤 A：`subprocess` 调原厂 `init_skill.py` 生成骨架，补写合规 `SKILL.md` frontmatter 与 `manifest.json`
   - 步骤 B：调 LLM（Skill Compiler 角色）生成并覆写 `executor.py`
   - 步骤 C：**质量关卡** = 原厂 `quick_validate`（SKILL.md 字段）+ **语法编译检测**（生成的 `executor.py`）。
     编译失败会把报错回喂模型**自愈重生一次**；`StagingResult.passed = valid AND compiled`。
   - 产物落在沙盒 `.staging_skills/{name}/`；身份偏好则 `stage_identity_update()` 落 `identity_patches.json`

4. **推送 + 挂载** `main_satellite.run_satellite_cycle()` 打印轨道观测报告并进入
   `while True` 确认循环：
   - `Y` → `shutil.move` 挪到正式 `skills/`，patches 按 `target` **分流并入** IDENTITY/SOUL/AGENTS/USER.md（写前留 `.bak`），清空沙盒
   - `N` → `shutil.rmtree` 清空沙盒
   - 其他文本 → 作为修改意见拼进 `compile_instruction`，重生成后再次确认

---

## 安装

```bash
cd skills/Satellite/meta_skill
python3 -m venv .venv
.venv/bin/pip install pydantic openai pyyaml
```

依赖说明：
- `pydantic` — 阶段二决策的严格 Schema 校验
- `openai` — OpenAI 兼容客户端（研判 + 代码生成 + 身份合并；DeepSeek 同样走它）
- `pyyaml` — 让原厂 `quick_validate` 走 YAML 主解析分支（缺失时有 fallback）

运行真实 LLM 需要配置 Provider（默认走 DeepSeek，见下方「接入 DeepSeek / OpenClaw」）：

```bash
export DEEPSEEK_API_KEY=sk-...     # 默认 provider=deepseek, 模型 deepseek-v4-pro
```

---

## 使用

### 一键跑完整周期

```bash
# 默认直读 memory/ 的 Markdown 记忆, 默认走 DeepSeek (需 DEEPSEEK_API_KEY)
DEEPSEEK_API_KEY=sk-... .venv/bin/python main_satellite.py --hours 72 -v
# 指定 provider / 模型:
.venv/bin/python main_satellite.py --provider deepseek --model deepseek-v4-pro
# 如需用 SQLite:
.venv/bin/python main_satellite.py --source sqlite --db /path/to/logs.db
```

常用参数：`--hours` 时间窗口、`--source markdown|sqlite`、`--memory` 记忆目录、
`--db`/`--table`（sqlite）、`--provider deepseek|openclaw|openai`、`--model`、
`--staging` 沙盒、`--skills-dir` 正式技能目录、
`--identity` 身份文件（默认与 `skills/` 同级的 `IDENTITY.md`，其同级目录即四件身份文件所在处）。

### 单阶段调试

```bash
# 阶段一：导出近 72h 日志
.venv/bin/python log_sniffer.py --db logs.db --hours 72 --pretty

# 阶段二：对一份日志 JSON 做研判
.venv/bin/python gateway_router.py logs.json --model gpt-4o-mini

# 阶段三：把一条指令编译成沙盒技能
.venv/bin/python executor_bridge.py my-skill --instruction "封装 X->Y，暴露 run()"
```

### 离线测试（无需 API Key）

各阶段测试都用注入的 Mock LLM，纯离线可跑：

```bash
.venv/bin/python test_log_sniffer.py
.venv/bin/python test_gateway_router.py
.venv/bin/python test_executor_bridge.py
.venv/bin/python test_skill_gateway.py
.venv/bin/python test_main_satellite.py
```

---

## 数据源

默认 `source="markdown"`，直读 OpenClaw 工作区记忆（无需任何数据库）：

- `memory/YYYY-MM-DD.md` —— 每日精炼笔记，按 `## 小节` 拆成记录（标题作 `user_intent`）。
- `memory/dreaming/**/*.md` —— 含 `Candidate: User:` / `Candidate: Assistant:` 的对话候选，
  解析成 user/assistant 配对；工具从文本启发式抽取（形如 `` use the `x` tool ``）。

按文件名日期（或 mtime）做时间窗过滤；记忆目录不存在时返回空（按"无日志"处理）。

仍可选 SQLite（`source="sqlite"`，列名经 `ColumnMap` 适配）：

```sql
CREATE TABLE interaction_logs (
    id INTEGER PRIMARY KEY, timestamp TEXT,
    user_input TEXT, assistant_response TEXT, tool_calls TEXT
);
```

## 运行时 Skill 网关 (`skill_gateway.py`)

与离线的 `gateway_router` 不同，这是**运行时**网关：

```bash
.venv/bin/python skill_gateway.py list                 # 发现并列出技能
.venv/bin/python skill_gateway.py match "提醒我明天开会"  # 触发匹配 + 仲裁
.venv/bin/python skill_gateway.py catalog              # 打印去重清单
```

能力：发现/编目、触发匹配（触发词加权打分）、优先级仲裁
（`temporary > user > builtin`，可被 `metadata.priority` 覆盖）、
热加载 `load_skill()` / 卸载 `unload_skill()` / 启停 `enable|disable()`、
以及动态 `invoke()`（导入技能 `executor.py` 调 `run()`）。

---

## 接入 DeepSeek / OpenClaw（LLM 客户端）

**Skill 是独立的 Python 进程，不会自动继承 OpenClaw 的模型路由或密钥。** 但你在
OpenClaw 里配的 DeepSeek 是 **OpenAI-completions 兼容**（`baseUrl: https://api.deepseek.com`），
所以本项目用同一个 `openai` SDK + `base_url` 即可直连。客户端统一由
`gateway_router.make_llm_client()` 按 env/参数构造，三种 provider：

| provider | base_url | 默认模型 | 取 key 的 env |
|----------|----------|----------|---------------|
| `deepseek`（默认） | `https://api.deepseek.com` | `deepseek-v4-pro` | `DEEPSEEK_API_KEY` |
| `openclaw` | `http://127.0.0.1:18789/v1` | `deepseek-v4-pro` | `OPENCLAW_GATEWAY_TOKEN` |
| `openai` | （SDK 默认） | `gpt-4o-mini` | `OPENAI_API_KEY` |

**方式 A — 直连 DeepSeek（推荐）。** 用你配置 OpenClaw deepseek provider 时的同一把
API key（OpenClaw 把它存在自己的密钥库/钥匙串里，不在 `openclaw.json` 明文）：

```bash
export DEEPSEEK_API_KEY=sk-...
.venv/bin/python main_satellite.py --provider deepseek --model deepseek-v4-pro
```

**方式 B — 走 OpenClaw 本地网关。** `openclaw.json` 已开
`gateway.http.endpoints.chatCompletions.enabled: true`（端口 18789，token 鉴权），
它本身就是 OpenAI 兼容端点，由 OpenClaw 路由到配置好的模型：

```bash
export OPENCLAW_GATEWAY_TOKEN=<gateway.auth.token>
.venv/bin/python main_satellite.py --provider openclaw
# 若端点路径不同, 用 SATELLITE_LLM_BASE_URL 覆盖
```

通用覆盖 env：`SATELLITE_LLM_PROVIDER` / `SATELLITE_LLM_MODEL` /
`SATELLITE_LLM_BASE_URL` / `SATELLITE_LLM_API_KEY`。

> 一句话答 Q2：**装完 OpenClaw 不会让 Skill 自动拿到 API**——你需要把 DeepSeek 的
> key（或网关 token）通过上面任一 env 暴露给这个独立进程；因为是 OpenAI 兼容协议，
> 之后无需改代码即可使用 `deepseek-v4-pro`。

---

## 身份/认知文件路由（自我进化的"修改身份"能力）

研判时每条认知补丁都带 `target`，挂载（`Y`）时由 `_apply_identity_updates()` 按
`target` 分组，分别**合并/修补**到与 `skills/` 同级的四个文件：

| target | 职责 | 典型补丁 |
|--------|------|----------|
| `IDENTITY.md` | 人设/名字/对外调性 | "管家自称固定为 Franziska" |
| `SOUL.md` | 灵魂/价值观/语气 | "回答多用学术、严谨的语气" |
| `AGENTS.md` | 工作方法/规则/约定 | "多选构建任务先出计划再动手" |
| `USER.md` | 关于**主人**的事实与偏好 | "用户近期在做视频伪造检测研究" |

合并策略（每个文件独立处理）：
- **有 LLM 客户端**：把该文件全文 + 待并入补丁交给模型，**语义相近的润色合并、
  全新内容入合适小节、不删无关内容**，整篇覆写。
- **无客户端 / LLM 失败**：确定性**去重追加**兜底（跳过明显重复的补丁）。
- 覆写前一律写 `*.md.bak` 备份（可回滚）。

> 一句话答 Q1：现在已经能根据需求**合并 + 修补** IDENTITY/SOUL/AGENTS/USER 四个文件
> （由网关 LLM 决定每条补丁路由到哪个文件），并自动去重润色、留备份。

---

## 三大「抑制」智能 · 现状

| 抑制规则 | 设计目标 | 当前实现 |
|----------|----------|----------|
| 复杂度过滤 | 单步操作（如查天气）不生成 Skill，转为身份偏好 | 🟡 System Prompt 已含"复杂度过滤"规则，软约束(无硬性代码门槛) |
| 重复性检测 | 生成前检索已有 Skill 库，可覆盖则放弃/升级 | ✅ `build_skill_catalog()` 扫 `skills/**/SKILL.md` 经 `extra_user_context` 喂网关；Prompt 规定 ignore/upgrade |
| 质量关卡 | 字段完整性 / 触发冲突 / 沙盒可达 / 风格一致 / 预览确认 | ✅ 字段完整性(quick_validate) + **编译检测(`executor.py` 语法编译, 失败自愈重生一次)** + 预览确认；🟡 触发词冲突检测、风格一致性仍未做 |

---

## 现状与限制（务必先读）

- ✅ **数据源已对接真实环境**：`log_sniffer` 默认 `source="markdown"`，直读
  `memory/*.md` 与 `memory/dreaming/**/*.md`（实测 541 条/30 文件）。SQLite 仍可选。
- ✅ **运行时网关已实现**：`skill_gateway.SkillGateway` 提供发现 / 触发匹配 /
  优先级仲裁 / 热加载卸载 / 生命周期 / 动态 `invoke()`。
- ✅ **重复性检测已接入**：`build_skill_catalog()` 把现有技能清单经
  `extra_user_context` 喂给网关，Prompt 规定命中即 ignore/upgrade。
- ✅ **身份/认知多文件路由已实现**：补丁带 `target`，挂载时分流并入
  IDENTITY/SOUL/AGENTS/USER.md（LLM 润色合并 + 去重兜底 + `.bak` 备份）。
- ✅ **编译质量关卡已补全**：生成的 `executor.py` 过语法编译检测，失败回喂报错自愈一次；
  `StagingResult.passed = valid AND compiled`。
- ✅ **LLM 客户端可配 DeepSeek/OpenClaw**：`make_llm_client()` 统一构造，默认 DeepSeek。
- **Skill Compiler 为通用 LLM 占位**：执行层代码由通用 LLM(文本模式)生成，
  尚未接入独立的 skill_compiler 工作流引擎（如 OpenClaw AceForge 插件）。
- **仅按需的「主动萃取」**：尚无「用户明说『把这套流程固定成技能』」的实时按需生成入口。
- **LLM 质量未实测**：所有验收均基于 Mock；真实模型（含 DeepSeek）产出稳定性未端到端验证。
- **周期**：默认 72h（3 天），与「以周为单位」的设想仍需对齐。

---

## Roadmap（剩余缺口）

1. 硬复杂度门槛：在代码层对「单步/低频」直接降级为身份偏好（目前仅 Prompt 软约束）。
2. 质量关卡再补：触发词冲突检测、风格一致性检查（编译检测已完成）。
3. 按需生成入口：交互式「需求澄清 → 工具抽取 → 流程编排」实时通道。
4. 增强 Skill Compiler：加入 LLM-as-Judge 合理性审查（compile_instruction 对齐度、run() 可达性、触发词冲突）。
5. 把 `skill_gateway` 接到实际对话入口，实现真正的运行时触发/热插拔闭环。
6. 调度接入：cron / heartbeat 周期触发，落地「主动萃取」。
```
