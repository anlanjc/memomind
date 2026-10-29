# LLMOpsDecider 真模型决策对比（规则决策矩阵基准，MM-3）

- 口径：决策层单变量对比——抽取层冻结为 RuleExtractor，两路喂完全相同的候选事实与 active 记忆快照（来自 eval_set_100 复放的决策点）；判定基准=规则决策矩阵输出（mock 评测 100/100 的同一套确定性金标）。
- 抽样：全量决策点分层抽样 44 个试验（每模式 ≤6），模式分布见下；LLM=deepseek-v4-flash（与抽取对比同模型同传输层）。
- 花费（usage 实测）：132 次调用，43616 in + 21898 out tokens ≈ ¥0.44（上限 ¥1.0），账本 evals/.real_ops_ledger.json。
- 传输层：curl(schannel) + NO_PROXY=dashscope.aliyuncs.com。

| 用例 | 输入 | 现有记忆 | 规则矩阵动作 | LLM 动作 | 判定 | 分歧 | LLM 理由 |
|---|---|---|---|---|---|---|---|
| A09#0 | 字节挂了 | 无 | ADD,('user', 'application_status', '字节跳动:ended') | ADD,('user', 'application_status', '字节跳动:ended') | √ | - | No existing memory for this user application status; adding as new fact. |
| A10#0 | 我现在在美团上班 | 无 | ADD,('user', 'works_at', '美团') | ADD,('user', 'works_at', '美团') | √ | - | 全新事实，无现有记忆冲突。 |
| A11#0 | 我在网易工作 | 无 | ADD,('user', 'works_at', '网易') | ADD,('user', 'works_at', '网易') | √ | - | 新事实，用户工作单位信息为空，直接添加 |
| A12#0 | 收到蚂蚁的面试邀请 | 无 | ADD,('user', 'application_status', '蚂蚁集团:interviewing') | ADD,('user', 'application_status', '蚂蚁集团:interviewing') | √ | - | 候选事实为全新事实，现有记忆中无相关内容。 |
| A15#0 | 收到字节的offer | 无 | ADD,('user', 'application_status', '字节跳动:offer') | ADD,('user', 'application_status', '字节跳动:offer') | √ | - | 无现有记忆，新增用户获得字节跳动 offer 的状态事实。 |
| A18#0 | 我在华为工作 | 无 | ADD,('user', 'works_at', '华为') | ADD,('user', 'works_at', '华为') | √ | - | 用户工作单位信息新增，现有记忆中不存在该事实 |
| A01#0 | 我投了字节 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 全新事实：用户申请了字节跳动; 全新事实：用户对字节跳动的申请状态为已提交 |
| A02#0 | 我投了阿里巴巴 | 无 | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | New fact: user applied to Alibaba, no existing memory conflicts.; New fact: application status is submitted for Alibaba, no existing memory conflicts. |
| A03#0 | 我投了蚂蚁 | 无 | ADD,('user', 'applied_to', '蚂蚁集团'); ADD,('user', 'application_status', '蚂蚁集团:submitted') | ADD,('user', 'applied_to', '蚂蚁集团'); ADD,('user', 'application_status', '蚂蚁集团:submitted') | √ | - | 用户申请蚂蚁集团，新事实; 用户申请状态为已提交，新事实 |
| A04#0 | 我投了字节的Agent岗 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 用户申请字节跳动，该信息不在现有记忆中，作为新事实添加。; 用户对字节跳动的申请状态为已提交，该信息不在现有记忆中，作为新事实添加。 |
| A05#0 | 投了deepseek | 无 | ADD,('user', 'applied_to', 'DeepSeek'); ADD,('user', 'application_status', 'DeepSeek:submitted') | ADD,('user', 'applied_to', 'DeepSeek'); ADD,('user', 'application_status', 'DeepSeek:submitted') | √ | - | New fact: user applied to DeepSeek; New fact: user's application status is submitted |
| A06#0 | 我投了快手 | 无 | ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 全新事实：用户申请了快手; 全新事实：快手的申请状态为已提交 |
| M02#0 | 我熟悉 Python、FastAPI 和 MySQL | 无 | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | √ | - | 全新事实，用户使用Python; 全新事实，用户使用FastAPI; 全新事实，用户使用MySQL |
| M10#0 | 我叫王芳，我投了腾讯 | 无 | ADD,('user', 'name', '王芳'); ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted') | ADD,('user', 'name', '王芳'); ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted') | √ | - | 全新事实，用户姓名为王芳; 全新事实，用户申请了腾讯; 全新事实，申请状态为已提交 |
| U15#0 | 我熟悉 Python、FastAPI 和 MySQL | 无 | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | √ | - | 用户使用Python，为全新事实; 用户使用FastAPI，为全新事实; 用户使用MySQL，为全新事实 |
| A08#0 | 我投了阿里和字节 | 无 | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 用户申请阿里巴巴，属于新事实; 阿里巴巴申请状态为已提交，是新增信息; 用户申请字节跳动，属于新事实; 字节跳动申请状态为已提交，是新增信息 |
| A19#0 | 我投了字节和阿里 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 全新事实：用户申请了字节跳动; 全新事实：字节跳动申请状态为已提交; 全新事实：用户申请了阿里巴巴; 全新事实：阿里巴巴申请状态为已提交 |
| M06#0 | 我投了腾讯和阿里 | 无 | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 用户申请腾讯，新事实; 腾讯申请状态为已提交，新事实; 用户申请阿里巴巴，新事实; 阿里巴巴申请状态为已提交，新事实 |
| U10#0 | 我投了美团和快手 | 无 | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 用户申请美团，新信息; 美团申请状态为已提交，新信息; 用户申请快手，新信息; 快手申请状态为已提交，新信息 |
| W06#0 | 我投了美团和快手 | 无 | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 用户申请了美团，这是全新事实。; 美团的申请状态为已提交，这是全新事实。; 用户申请了快手，这是全新事实。; 快手的申请状态为已提交，这是全新事实。 |
| W15#0 | 我投了腾讯和阿里 | 无 | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 用户申请腾讯，全新事实; 腾讯申请状态为已提交，全新事实; 用户申请阿里巴巴，全新事实; 阿里巴巴申请状态为已提交，全新事实 |
| S-A0#0 | （合成）低置信丢弃：一条0.2置信的偏好 | 无 | NOOP | NOOP | √ | - | 低置信度(0.20)，丢弃 |
| S-B2#0 | （合成）完全重复同置信：已投美团(0.9)，再投美团(0.9) | (applied_to,美团) | NOOP | NOOP | √ | - | 完全重复，跳过 |
| A14#1 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复，跳过; 完全重复，跳过 |
| U09#1 | 我投了腾讯 | (applied_to,腾讯); (application_status,腾讯:submitted) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复，跳过; 完全重复，跳过 |
| U14#1 | 我投了字节 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复，跳过; 完全重复，跳过 |
| S-B1#0 | （合成）重复提及且置信更高：已投美团(0.9)，再投美团(0.95) | (applied_to,美团) | UPDATE,strengthen,('user', 'applied_to', '美团') | UPDATE,strengthen,('user', 'applied_to', '美团') | √ | - | 重复提及，合并强化置信度 |
| S-B1S#0 | （合成）技能重复强化：已会Python(0.8)，再说熟悉Python(0.85) | (uses,Python) | UPDATE,strengthen,('user', 'uses', 'Python') | UPDATE,strengthen,('user', 'uses', 'Python') | √ | - | 重复提及，合并强化置信度 |
| U08#1 | 我掌握 Python | (uses,Python) | UPDATE,strengthen,('user', 'uses', 'Python') | UPDATE,strengthen,('user', 'uses', 'Python') | √ | - | 重复提及，合并强化置信度 |
| A01#1 | 字节跳动的流程结束了 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | √ | - | 新事实表明字节跳动应聘状态已从submitted变为ended，应更新原状态记忆。 |
| A03#1 | 蚂蚁的流程结束了 | (application_status,蚂蚁集团:submitted); (applied_to,蚂蚁集团) | UPDATE,supersede,('user', 'application_status', '蚂蚁集团:submitted'),('user', 'application_status', '蚂蚁集团:ended') | UPDATE,supersede,('user', 'application_status', '蚂蚁集团:submitted'),('user', 'application_status', '蚂蚁集团:ended') | √ | - | Latest status indicates application ended, supersedes previous submitted status with higher confidence. |
| A06#1 | 收到快手的面试邀请 | (applied_to,快手); (application_status,快手:submitted) | UPDATE,supersede,('user', 'application_status', '快手:submitted'),('user', 'application_status', '快手:interviewing') | UPDATE,supersede,('user', 'application_status', '快手:submitted'),('user', 'application_status', '快手:interviewing') | √ | - | 用户对快手的申请状态从 submitted 更新为 interviewing，以新状态覆盖旧状态。 |
| A10#1 | 我现在在字节上班 | (works_at,美团) | UPDATE,supersede,('user', 'works_at', '美团'),('user', 'works_at', '字节跳动') | UPDATE,supersede,('user', 'works_at', '美团'),('user', 'works_at', '字节跳动') | √ | - | New fact indicates user works at ByteDance, contradicting existing memory that user works at Meituan; new fact takes precedence. |
| A11#1 | 我在字节跳动工作 | (works_at,网易) | UPDATE,supersede,('user', 'works_at', '网易'),('user', 'works_at', '字节跳动') | UPDATE,supersede,('user', 'works_at', '网易'),('user', 'works_at', '字节跳动') | √ | - | 新记忆表明用户现在在字节跳动工作，与旧记忆（网易）存在冲突，新事实生效并取代旧记忆。 |
| A17#1 | 字节挂了 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | √ | - | 新事实表明字节跳动申请状态已从submitted变为ended，应用新状态并标记旧记忆为已取代。 |
| A13#0 | 不想投字节了 | 无 | ADD,('user', 'withdrawn', '字节跳动') | ADD,('user', 'withdrawn', '字节跳动') | √ | - | 撤销意图（无对应记忆），留档 |
| W04#0 | 不想投腾讯了 | 无 | ADD,('user', 'withdrawn', '腾讯') | ADD,('user', 'withdrawn', '腾讯') | √ | - | 撤销意图（无对应记忆），留档 |
| W11#2 | 不想投京东了 | (withdrawn,京东) | ADD,('user', 'withdrawn', '京东') | ADD,('user', 'withdrawn', '京东') | √ | - | 撤销意图（无对应记忆），留档 |
| A02#1 | 取消阿里的申请 | (application_status,阿里巴巴:submitted); (applied_to,阿里巴巴) | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user application_status 阿里巴巴:submitted; 撤销：失效 user applied_to 阿里巴巴; 撤销事实留档（审计可查） |
| A19#1 | 取消阿里的申请 | (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted); (applied_to,字节跳动); (application_status,字节跳动:submitted) | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user applied_to 阿里巴巴; 撤销：失效 user application_status 阿里巴巴:submitted; 撤销事实留档（审计可查） |
| D09#1 | 取消腾讯的申请 | (application_status,腾讯:submitted); (applied_to,腾讯) | DELETE,('user', 'application_status', '腾讯:submitted'); DELETE,('user', 'applied_to', '腾讯'); ADD,('user', 'withdrawn', '腾讯') | DELETE,('user', 'application_status', '腾讯:submitted'); DELETE,('user', 'applied_to', '腾讯'); ADD,('user', 'withdrawn', '腾讯') | √ | - | 撤销：失效 user application_status 腾讯:submitted; 撤销：失效 user applied_to 腾讯; 撤销事实留档（审计可查） |
| M12#1 | 取消阿里的申请 | (application_status,阿里巴巴:submitted); (applied_to,阿里巴巴) | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user application_status 阿里巴巴:submitted; 撤销：失效 user applied_to 阿里巴巴; 撤销事实留档（审计可查） |
| S-C1M#0 | （合成）撤销命中两条：已投美团+已提交，再说取消美团申请 | (applied_to,美团); (application_status,美团:submitted) | DELETE,('user', 'applied_to', '美团'); DELETE,('user', 'application_status', '美团:submitted'); ADD,('user', 'withdrawn', '美团') | DELETE,('user', 'applied_to', '美团'); DELETE,('user', 'application_status', '美团:submitted'); ADD,('user', 'withdrawn', '美团') | √ | - | 撤销：失效 user applied_to 美团; 撤销：失效 user application_status 美团:submitted; 撤销事实留档（审计可查） |
| S-MIX#0 | （合成）混合批：新投快手+同时取消腾讯（腾讯在库） | (applied_to,腾讯); (application_status,腾讯:submitted) | ADD,('user', 'applied_to', '快手'); DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | ADD,('user', 'applied_to', '快手'); DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | √ | - | New fact: user applied to 快手, not present in existing memories.; 撤销：失效 user applied_to 腾讯; 撤销：失效 user application_status 腾讯:submitted; 撤销事实留档（审计可查） |

## 汇总

- 动作序列完全一致：**44/44 = 100%**；多重集一致（含顺序差）：44/44
- LLM 异常回退（fallback_error）：0/44；结构性分支委托规则版（撤销/重复提及 UPDATE 定位）按试样统计见 llm_stats 字段
- 分层一致率见下表（合成-语义探针层 = 矩阵分支的最小合成试验）。

| 层 | 一致/试验 |
|---|---|
| 事实更新 | 5/5 |
| 冲突撤回 | 4/4 |
| 别名归一 | 24/24 |
| 合成-语义探针 | 6/6 |
| 多跳召回 | 4/4 |
| 时序衰减 | 1/1 |

## 分歧模式分布

```
```

## 分析

**修复路径（四轮复测，花费全程 usage 实记账本）：31/44=70.5% → 41/44=93% →
43/44=98% → 44/44=100%。** phase1 是 LLMOpsDecider 原始行为（整批交 LLM 裁决），
phase2-4 是逐类分歧加固后的复测——两个口径都必须报：raw 70.5% 是"LLM 决策
开箱即用"的真实水平，100% 是"结构分支委托后"的终态。

**分歧模式量化（phase1 → 归因 → 加固）**

1. **撤销复合动作丢失（C1 分支，6/6 全分歧）**：规则矩阵对撤销产出
   DELETE(逐条目标)+ADD(留档) 复合动作；LLM 的输出 schema 是"每条候选事实
   一个动作"，表达不了复合动作——phase1 实测它要么回一个 UPDATE:supersede
   （把 withdrawn 事实创造性替换掉 applied_to 记忆，丢状态记录与留档）、
   要么 NOOP（W11 重复撤销）。归因=**输出 schema 表达力**，不是判断力。
   加固：撤销事实整体委托规则版（零 LLM 调用），动作置于批内最后。
2. **重复提及置信算术（B1/B2 分支，两轮各 1-2 条）**：strengthen/NOOP 由
   confidence 比较决定；LLM phase1 说 UPDATE（语义被塌缩成 supersede——
   LLMOpsDecider 无 strengthen 表达）、phase2/3 对同输入说 NOOP——**运行间
   摇摆**。归因=置信度算术 + 判定波动。加固：同三元组重复在进 LLM 前
   预路由规则版。
3. **低置信策略阈值（A0 分支，1 条）**：0.2 置信事实 LLM 判 ADD（理由原话：
   "尽管置信度较低，仍可添加以供参考"）——它不知道 min_confidence=0.30 是
   **可配置策略**。归因=配置不可见。加固：低置信预路由规则版丢弃。
4. **LLM 判断正确的域（语义核心）**：纯新增 21 试样全一致（含多公司伴随对
   批）、矛盾替代（target_role/状态推进 D1）、混合批、无冲突新偏好——
   E1/D1/D2 类语义判断 132 次调用零异常、零回退（fallback_error=0）。

**评测装置 bug（本轮发现并修复）**：collect_trials 首版把快照直接交给
规则决策器，strengthen 的 _advance_state 会改写 state 里的记录对象
（0.85→0.93），导致规则"看到改写前状态判 strengthen"、LLM"看到改写后
状态判 NOOP"——单变量对比被破坏。修复=快照 deepcopy 隔离。教训：**对比
评测里"两路输入字节级相同"要靠机制保证，不能靠自觉**。

**结论（ADR-6）**：LLM 决策器收敛为"规则矩阵的结构化分支 + LLM 语义核心"——
A0 低置信丢弃 / B1B2 重复强化 / C1 撤销复合动作委托规则矩阵，LLM 保留
E1 新增 / D1 矛盾替代 / D2 多值并存的判断。分歧的根因是**输出 schema
表达力与策略配置可见性**，不是 LLM 判断力；委托后 44/44 与矩阵一致，
且每次决策的 delegated_*/fallback_error 留痕可观测。

**诚实边界**：44 试样来自 180 个决策点的分层抽样（每模式 ≤6）+ 9 个合成
语义探针（覆盖 eval 集复放覆盖不到的 B1/B2/A0/多目标撤销分支）；
100% 是加固后口径，raw 70.5% 同样留档（phase1 rows）；LLM 在 novel 事实
上的自由判断仍可能翻车（本窗口未见，词典/用例按活档案机制扩充）；
同批内"先撤后投"等极端顺序语义以规则矩阵为准（抽取层已按三元组批内
去重，精确重复到不了决策层）。花费：phase1 ¥0.25（.real_ops_ledger_phase1.json）
+ phase2-4 ¥0.44（.real_ops_ledger.json，132 次调用）= **¥0.69 ≤ ¥1**。
