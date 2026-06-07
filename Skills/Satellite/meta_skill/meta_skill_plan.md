MetaSkill (生成Skill的Skill) 架构与 SOP
1. 极简双层架构
网关层（策略大脑）：3天为周期的嗅探器。负责分析历史对话，提取多工具调用习惯、近期关注点，并识别用户明确的需求。输出决策（是否合并/升级Skill，是否更新身份预设）。
执行层（生成手脚）：将网关决策转化为实际操作。结合 create-skill（生成目录和声明）和 Skill Compiler（编译核心逻辑代码），完成新技能的沙盒生成。
2. 四阶段 SOP
阶段一：嗅探与聚合 -> 从 SQLite 提取过去 3 天包含工具调用的对话日志，清洗并序列化。
阶段二：网关决策 -> 大模型根据 System Prompt 研判日志，输出严格的结构化 JSON 决策。
阶段三：执行编译 -> 结合 Skill Compiler + create-skill，在 .staging_skills/ 沙盒目录生成代码。
阶段四：主动推送与挂载 -> 向用户发消息确认，同意后热加载挂载到正式环境，或更新 IDENTITY.md/SOUL.md。
