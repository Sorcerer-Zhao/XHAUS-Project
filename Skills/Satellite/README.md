# 🛰️ Satellite — MetaSkill（生成 Skill 的 Skill）

> 让管家具备自我进化能力的元技能：从重复的问答循环中自动萃取模式，
> 形成可复用的 Skill 或身份偏好，经用户确认后挂载到正式环境。

Satellite 是一个**双层、四阶段**流水线：

- **网关层（策略大脑）**：周期性嗅探历史对话 + 记忆召回 + 能力快照，做结构化研判。
- **执行层（生成手脚）**：把研判结果编译成沙盒里的真实技能（提案驱动或文本驱动），再由用户拍板挂载。

与早期版本相比，当前架构增加了三层「结构化中间态」，避免把全部逻辑塞进 Prompt：

1. **记忆索引**（`log_sniffer`）— chunk 化日志、关键词召回、能力缺口快照。
2. **Skill 机会挖掘**（`gateway_router`）— 先判断复用 / 工具链封装 / 最小提案 / 无动作，再联动 `skill_generation`。
3. **提案驱动编译**（`executor_bridge`）— `SkillProposal` → `compile_instruction` → 脚手架 / 代码生成 / 质检。

---

## 架构总览

```
  Markdown / SQLite
  memory/          ┌──────────────────── 网关层 (策略大脑) ────────────────────────────┐
       │           │  阶段一 嗅探 + 记忆索引                                              │
       └──────────▶│  log_sniffer.sniff()                                                 │
                   │    ├─ cleaned logs (紧凑 JSON, 兼容旧接口 result.json)               │
                   │    ├─ MemoryChunk 索引 + retrieve_relevant_memory()                  │
                   │    └─ CapabilitySnapshot (TOOLS.md keys / skills/ / gaps)           │
                   │                         │                                            │
                   │  阶段二 研判 (两段式 Skill 机会判断)                                  │
                   │  gateway_router.evaluate_habits(                                     │
                   │      logs_json, retrieved_memory, trait_memory, capability_snapshot) │
                   │    ├─ build_skill_catalog() ──▶ 去重清单 (extra_user_context)        │
                   │    ├─ LLM → skill_opportunity + skill_generation + identity_update   │
                   │    └─ reconcile_gateway_decision() (Python 结构化后处理)            │
                   │                         │                                            │
                   │                         ▼ GatewayDecision                            │
                   └─────────────────────────┴────────────────────────────────────────────┘
                                             │
                   ┌─────────────────────────▼──────────────────────────────────────────┐
                   │  阶段三 编译 (提案驱动 或 纯文本)                                         │
                   │  executor_bridge                                                         │
                   │    should_stage_skill(decision)                                        │
                   │      ├─ tool_chain_composition → generate_skill_from_proposal()        │
                   │      ├─ new_skill_proposal     → expand_minimal_proposal() + draft     │
                   │      └─ 旧路径 / 回退          → generate_skill_to_staging()            │
                   │    共享流水线: init_skill.py → LLM(executor.py) → quick_validate       │
                   │              + py_compile (失败自愈重生一次)                            │
                   │    产物: .staging_skills/{name}/                                       │
                   │      SKILL.md, executor.py, manifest.json, skill_proposal.json         │
                   └─────────────────────────┬──────────────────────────────────────────────┘
                                             │
                   ┌─────────────────────────▼──────────────────────────────────────────┐
                   │  阶段四 推送 + 挂载  main_satellite.run_satellite_cycle()              │
                   │    终端报告 + Human-in-the-Loop                                        │
                   │    [Y] 挂载 skills/ + 按 target 并入 IDENTITY/SOUL/AGENTS/USER.md      │
                   │    [N] 清空沙盒                                                          │
                   │    [其他] 回炉重构 (compile_instruction 追加意见后重生成)               │
                   └──────────────────────────────────────────────────────────────────────┘

  运行时 (独立)     skill_gateway.SkillGateway — 发现 / 触发匹配 / 仲裁 / 热加载 / invoke()
```

---

## 模块清单

| 文件 | 阶段 | 角色 | 关键 API |
|------|------|------|----------|
| `meta_skill_plan.md` | — | 全局规划与 SOP | — |
| `log_sniffer.py` | 一 | 日志嗅探 + **记忆索引** + **能力快照** | `sniff()`, `chunk_logs()`, `retrieve_relevant_memory()`, `sniff_capabilities_structured()`, `SnifferResult` |
| `gateway_router.py` | 二 | LLM 策略研判 + **Skill 机会挖掘** + 补丁路由 | `evaluate_habits()`, `GatewayDecision`, `SkillOpportunityDecision`, `reconcile_gateway_decision()`, `is_skill_execution_ready()`, `make_llm_client()` |
| `executor_bridge.py` | 三 | **提案驱动**编译 + 脚手架 + 质检 | `SkillProposal`, `generate_skill_from_proposal()`, `proposal_from_gateway_decision()`, `should_stage_skill()`, `generate_skill_to_staging()`, `stage_identity_update()` |
| `skill_gateway.py` | 运行时 | 运行时网关：发现/匹配/仲裁/热加载/`invoke()` + 去重清单 | `SkillGateway`, `build_skill_catalog()` |
| `main_satellite.py` | 四 | 串联全流程 + HIL + 多文件身份合并 | `run_satellite_cycle()`, `_apply_identity_updates()` |
| `test_*.py` | — | 各模块离线 mock 验收 (5 套) | — |

目录结构：

```
skills/Satellite/
├── SKILL.md              # OpenClaw 挂载入口
├── README.md
└── meta_skill/           # 全部 Python 代码 + .venv
    ├── log_sniffer.py
    ├── gateway_router.py
    ├── executor_bridge.py
    ├── skill_gateway.py
    ├── main_satellite.py
    └── test_*.py
```

---

## 数据流（逐阶段）

### 阶段一：嗅探 + 记忆索引

`log_sniffer.sniff(hours=72)` 抓取近 N 小时记录，返回 `SnifferResult`：

| 字段 | 说明 |
|------|------|
| `result.json` | **兼容旧接口**：仅 cleaned logs 的紧凑 JSON 数组 |
| `result.chunks` | 全量 `MemoryChunk` 索引（含 `chunk_id`, `tags`, `tool_names` 等） |
| `result.retrieved_chunks` | 关键词召回结果（默认自动合成 `retrieve_query`） |
| `result.retrieve_query` | 实际用于召回的查询串（显式传入或 `build_retrieve_query()` 合成） |
| `result.capability_snapshot` | workspace 能力快照（API keys / 已有 skills / 预判缺口） |

**自动召回**（`sniff(auto_retrieve_query=True)`，默认开启）：

未显式传 `retrieve_query` 时，`build_retrieve_query()` 从以下来源合成查询：

1. 带 `explicit_instruction` / `preference` 标签的 chunk
2. 最近 6 条 `user_intent`
3. 高频 `tools_used` 工具名（重复工具链信号）
4. `CapabilitySnapshot.gaps` 中的 API 名（能力缺口）
5. `research` / `planning` 类 chunk 的用户首句

`main_satellite` 会把 `result.retrieved_json` 注入网关 `<RETRIEVED_MEMORY>`。

日志条目 schema（不变）：

```json
[{"timestamp":"…","user_intent":"…","tools_used":[{"name":"…","args":{}}],"assistant_response":"…"}]
```

### 阶段二：研判（两段式 Skill 机会判断）

`gateway_router.evaluate_habits()` 接收多段上下文：

- `<LOGS_JSON>` — 紧凑对话数组
- `<RETRIEVED_MEMORY>` — 高相关记忆 chunk
- `<TRAIT_MEMORY>` — 用户特质 / 显式偏好 chunk（如 `explicit_instruction` 标签）
- `<CAPABILITY_SNAPSHOT>` — 结构化能力快照
- `# 额外上下文` — 现有技能清单（`build_skill_catalog()`）等

**判断优先级**（后者不得压过前者）：

0. 显式指令（最高）
1. 能力缺口（TOOLS.md 有 key 但 skills/ 无对应 Skill）
2. 重复工具链
3. 工具链稳定性
4. 认知偏好（主要进 `identity_update`）

LLM 产出 JSON 后，经 Pydantic 校验 + **`reconcile_gateway_decision()`** 做 Python 层结构化对齐（非纯自然语言总结器）。

`GatewayDecision` schema：

```json
{
  "skill_opportunity": {
    "decision": "reuse_existing_skill | tool_chain_composition | new_skill_proposal | do_nothing",
    "matched_skills": ["existing-skill"],
    "missing_capabilities": ["amap-routing-api"],
    "tool_chain_signature": "fetch_url->extract_keywords",
    "new_skill_spec": {
      "name": "kebab-case-name",
      "description": "一句话",
      "proposed_triggers": ["触发词"],
      "tool_chain": ["fetch_url", "extract_keywords"],
      "rationale": "为何值得"
    },
    "decision_reason": "结构化理由"
  },
  "skill_generation": {
    "action": "merge | upgrade | suggest | ignore",
    "target_name": "kebab-case",
    "description": "一句话",
    "compile_instruction": "仅 merge/upgrade 时详细；proposal 时留空",
    "matched_skills": [],
    "missing_capabilities": [],
    "new_skill_spec": { "...同上..." }
  },
  "identity_update": {
    "action": "update | ignore",
    "patches": [{"target": "USER.md", "content": "…"}]
  }
}
```

**`skill_opportunity.decision` 四态**：

| decision | 含义 | 典型 `skill_generation.action` | 是否进 Skill Compiler |
|----------|------|-------------------------------|----------------------|
| `reuse_existing_skill` | 已有 Skill 可覆盖，不新建 | `ignore` | 否 |
| `tool_chain_composition` | 稳定重复工具链，值得封装复合 Skill | `merge` / `upgrade` | 是（完整提案） |
| `new_skill_proposal` | 有苗头，先出最小提案 | `suggest` | 是（最小草案，`minimal_draft=True`） |
| `do_nothing` | 本周期无 Skill 机会 | `ignore` | 否 |

`skill_opportunity` 缺省时由 `infer_default_skill_opportunity()` 从 `skill_generation` 反向推断，保持向后兼容。

### 阶段三：编译（提案驱动）

主路径（`main_satellite` 默认）：

```
GatewayDecision
  → should_stage_skill(decision) → (should_stage, minimal_draft)
  → proposal_from_gateway_decision(decision) → SkillProposal
  → generate_skill_from_proposal(proposal, minimal_draft=…)
      → (可选) expand_minimal_proposal()
      → compile_instruction_from_proposal()
      → _generate_skill_core()  # 共享内核
```

`SkillProposal` 字段：`name`, `purpose`, `trigger_condition`, `inputs`, `outputs`, `required_tools`, `steps`, `success_criteria`, `failure_modes`。

**两条编译路径**：

| 路径 | 入口 | 适用场景 |
|------|------|----------|
| 提案驱动 | `generate_skill_from_proposal()` | `tool_chain_composition` / `new_skill_proposal` |
| 纯文本（保留） | `generate_skill_to_staging(target_name, compile_instruction)` | 单阶段调试、旧调用方、无 proposal 时的回退 |

共享流水线步骤：

- **A** `init_skill.py` 脚手架 → 补写合规 `SKILL.md` frontmatter（`purpose` 优先）+ `manifest.json` + `skill_proposal.json`
- **B** LLM（Skill Compiler）生成并覆写 `executor.py`
- **C** 质量关卡 = 原厂 `quick_validate` + **`py_compile` 语法检测**（失败自愈重生一次）

`StagingResult.passed = valid AND compiled`。

身份偏好：`stage_identity_update()` → `.staging_skills/identity_patches.json`。

### 阶段四：推送 + 挂载

`main_satellite.run_satellite_cycle()` 打印轨道观测报告（含 Skill 机会层说明）并进入 HIL 循环：

- `Y` → 挂载 `skills/` + patches 按 `target` 分流并入四份身份文件（写前 `.bak`）
- `N` → 清空沙盒
- 其他文本 → 拼进 `compile_instruction` 回炉重构

`new_skill_proposal` 也会生成可审阅沙盒（标注为「最小提案草案」），但网关层不写长 `compile_instruction`。

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
.venv/bin/python log_sniffer.py --hours 72 --pretty

# 阶段二：对一份日志 JSON 做研判
.venv/bin/python gateway_router.py logs.json --model gpt-4o-mini

# 阶段三：纯文本路径编译沙盒技能
.venv/bin/python executor_bridge.py my-skill --instruction "封装 X->Y，暴露 run()"

# 阶段三：提案路径（在 Python 中）
# from executor_bridge import SkillProposal, generate_skill_from_proposal
# generate_skill_from_proposal(SkillProposal(name="...", purpose="...", ...))
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

chunk 级记忆带 `tags`（如 `tool_use`, `explicit_instruction`, `dialogue`），供网关 `trait_memory` 与召回加权使用。

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

## 抑制与质量 · 现状

| 规则 | 设计目标 | 当前实现 |
|------|----------|----------|
| **Skill 机会挖掘** | 先判断复用 vs 新建 vs 提案，再决定是否编译 | ✅ `skill_opportunity` 四态 + `reconcile_gateway_decision()` |
| **能力缺口优先** | TOOLS.md 有 key 但无 Skill → 倾向提案 | ✅ Prompt 优先级 + `CapabilitySnapshot.gaps` 注入 |
| **复杂度过滤** | 单步操作不生成 Skill，转为身份偏好 | 🟡 System Prompt 软约束（无硬性代码门槛） |
| **重复性检测** | 生成前比对已有 Skill 库 | ✅ `build_skill_catalog()` + `reuse_existing_skill` |
| **提案驱动编译** | 结构化输入，非纯文本 | ✅ `SkillProposal` → `compile_instruction_from_proposal()` |
| **质量关卡** | 字段 / 语法 / 预览确认 | ✅ `quick_validate` + `py_compile`（失败自愈一次）+ HIL 预览；🟡 触发词冲突、风格一致性未做 |

---

## 现状与限制（务必先读）

- ✅ **数据源已对接真实环境**：`log_sniffer` 默认 `source="markdown"`，直读
  `memory/*.md` 与 `memory/dreaming/**/*.md`。SQLite 仍可选。
- ✅ **记忆索引层**：`chunk_logs()`、`build_retrieve_query()`、`retrieve_relevant_memory()`、
  `CapabilitySnapshot`；`sniff()` 默认自动合成 `retrieve_query` 并召回相关 chunk。
- ✅ **Skill 机会挖掘层**：`skill_opportunity` 四态、两段式 Prompt、Python `reconcile` 对齐；
  `evaluate_habits()` 消费召回记忆 + 能力快照 + 特质记忆。
- ✅ **提案驱动执行层**：`generate_skill_from_proposal()` 与纯文本 `generate_skill_to_staging()` 并存；
  沙盒产出 `skill_proposal.json`。
- ✅ **运行时网关**：`skill_gateway.SkillGateway` 提供发现 / 触发匹配 / 仲裁 / 热加载 / `invoke()`。
- ✅ **身份/认知多文件路由**：补丁带 `target`，LLM 润色合并 + 去重兜底 + `.bak`。
- ✅ **编译质量关卡**：`StagingResult.passed = valid AND compiled`。
- ✅ **LLM 客户端可配 DeepSeek/OpenClaw**：`make_llm_client()` 统一构造。
- **Skill Compiler 为通用 LLM 占位**：执行层代码由通用 LLM（文本模式）生成，
  尚未接入独立的 skill_compiler 工作流引擎（如 OpenClaw AceForge 插件）。
- **仅按需的「主动萃取」**：尚无「用户明说『把这套流程固定成技能』」的实时按需生成入口。
- **LLM 质量未实测**：所有验收均基于 Mock；真实模型产出稳定性未端到端验证。
- **周期**：默认 72h（3 天），与「以周为单位」的设想仍需对齐。

---

## Roadmap（剩余缺口）

1. 硬复杂度门槛：在代码层对「单步/低频」直接降级为身份偏好（目前仅 Prompt 软约束）。
2. 质量关卡再补：触发词冲突检测、风格一致性检查。
3. 按需生成入口：交互式「需求澄清 → 工具抽取 → 流程编排」实时通道。
4. 增强 Skill Compiler：LLM-as-Judge 合理性审查（proposal 对齐度、`run()` 可达性）。
5. 把 `skill_gateway` 接到实际对话入口，实现真正的运行时触发/热插拔闭环。
6. 调度接入：cron / heartbeat 周期触发，落地「主动萃取」。
7. 记忆召回升级：从关键词 stub 过渡到 embedding 检索。
