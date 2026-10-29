# LLMOpsDecider 真模型决策对比（规则决策矩阵基准，MM-3）

- 口径：决策层单变量对比——抽取层冻结为 RuleExtractor，两路喂完全相同的候选事实与 active 记忆快照（来自 eval_set_100 复放的决策点）；判定基准=规则决策矩阵输出（mock 评测 100/100 的同一套确定性金标）。
- 抽样：全量决策点分层抽样 44 个试验（每模式 ≤6），模式分布见下；LLM=deepseek-v4-flash（与抽取对比同模型同传输层）。
- 花费（usage 实测）：44 次调用，14579 in + 8015 out tokens ≈ ¥0.15（上限 ¥1.0），账本 evals/.real_ops_ledger.json。
- 传输层：curl(schannel) + NO_PROXY=dashscope.aliyuncs.com。

| 用例 | 输入 | 现有记忆 | 规则矩阵动作 | LLM 动作 | 判定 | 分歧 | LLM 理由 |
|---|---|---|---|---|---|---|---|
| A09#0 | 字节挂了 | 无 | ADD,('user', 'application_status', '字节跳动:ended') | ADD,('user', 'application_status', '字节跳动:ended') | √ | - | 新增用户字节跳动申请状态为已结束的事实 |
| A10#0 | 我现在在美团上班 | 无 | ADD,('user', 'works_at', '美团') | ADD,('user', 'works_at', '美团') | √ | - | 新事实，无现有记忆冲突 |
| A11#0 | 我在网易工作 | 无 | ADD,('user', 'works_at', '网易') | ADD,('user', 'works_at', '网易') | √ | - | 全新事实，现有记忆为空 |
| A12#0 | 收到蚂蚁的面试邀请 | 无 | ADD,('user', 'application_status', '蚂蚁集团:interviewing') | ADD,('user', 'application_status', '蚂蚁集团:interviewing') | √ | - | 无现有记忆，全新事实 |
| A15#0 | 收到字节的offer | 无 | ADD,('user', 'application_status', '字节跳动:offer') | ADD,('user', 'application_status', '字节跳动:offer') | √ | - | 全新事实，用户申请状态为字节跳动offer |
| A18#0 | 我在华为工作 | 无 | ADD,('user', 'works_at', '华为') | ADD,('user', 'works_at', '华为') | √ | - | 新事实：用户工作于华为 |
| A01#0 | 我投了字节 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 新事实：用户已申请字节跳动; 新事实：用户对字节跳动的申请状态为已提交 |
| A02#0 | 我投了阿里巴巴 | 无 | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 全新事实：用户申请了阿里巴巴; 全新事实：用户对阿里巴巴的申请状态为已提交 |
| A03#0 | 我投了蚂蚁 | 无 | ADD,('user', 'applied_to', '蚂蚁集团'); ADD,('user', 'application_status', '蚂蚁集团:submitted') | ADD,('user', 'applied_to', '蚂蚁集团'); ADD,('user', 'application_status', '蚂蚁集团:submitted') | √ | - | 全新事实：用户申请了蚂蚁集团; 全新事实：用户对蚂蚁集团的申请状态为已提交 |
| A04#0 | 我投了字节的Agent岗 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 全新事实：用户申请了字节跳动; 全新事实：用户对字节跳动的申请状态为已提交 |
| A05#0 | 投了deepseek | 无 | ADD,('user', 'applied_to', 'DeepSeek'); ADD,('user', 'application_status', 'DeepSeek:submitted') | ADD,('user', 'applied_to', 'DeepSeek'); ADD,('user', 'application_status', 'DeepSeek:submitted') | √ | - | 全新事实：用户申请了DeepSeek; 全新事实：申请状态已提交 |
| A06#0 | 我投了快手 | 无 | ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 用户申请快手的全新事实，记忆库中不存在。; 用户申请状态为已提交的全新事实，记忆库中不存在。 |
| M02#0 | 我熟悉 Python、FastAPI 和 MySQL | 无 | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | √ | - | New fact: user uses Python.; New fact: user uses FastAPI.; New fact: user uses MySQL. |
| M10#0 | 我叫王芳，我投了腾讯 | 无 | ADD,('user', 'name', '王芳'); ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted') | ADD,('user', 'name', '王芳'); ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted') | √ | - | 用户姓名新事实，记忆中不存在，直接添加; 用户申请腾讯为新事实，记忆中不存在，直接添加; 用户申请腾讯状态为已提交，新事实，直接添加 |
| U15#0 | 我熟悉 Python、FastAPI 和 MySQL | 无 | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | √ | - | 新事实：用户使用 Python; 新事实：用户使用 FastAPI; 新事实：用户使用 MySQL |
| A08#0 | 我投了阿里和字节 | 无 | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 全新事实：用户申请了阿里巴巴; 全新事实：阿里巴巴申请状态为已提交; 全新事实：用户申请了字节跳动; 全新事实：字节跳动申请状态为已提交 |
| A19#0 | 我投了字节和阿里 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 全新事实：用户申请了字节跳动; 全新事实：用户申请字节跳动的状态为已提交; 全新事实：用户申请了阿里巴巴; 全新事实：用户申请阿里巴巴的状态为已提交 |
| M06#0 | 我投了腾讯和阿里 | 无 | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 用户申请腾讯，全新事实; 腾讯申请状态为已提交，全新事实; 用户申请阿里巴巴，全新事实; 阿里巴巴申请状态为已提交，全新事实 |
| U10#0 | 我投了美团和快手 | 无 | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 全新事实：用户申请了美团; 全新事实：美团申请状态为已提交; 全新事实：用户申请了快手; 全新事实：快手申请状态为已提交 |
| W06#0 | 我投了美团和快手 | 无 | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 用户申请美团的候选事实为全新信息; 美团申请状态为已提交，属于新事实; 用户申请快手的候选事实为全新信息; 快手申请状态为已提交，属于新事实 |
| W15#0 | 我投了腾讯和阿里 | 无 | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 用户申请了腾讯，新事实; 用户申请腾讯的状态为已提交，新事实; 用户申请了阿里巴巴，新事实; 用户申请阿里巴巴的状态为已提交，新事实 |
| S-A0#0 | （合成）低置信丢弃：一条0.2置信的偏好 | 无 | NOOP | NOOP | √ | - | 候选事实置信度过低（0.2），且无现有记忆支撑，暂不加入长期记忆 |
| S-B2#0 | （合成）完全重复同置信：已投美团(0.9)，再投美团(0.9) | (applied_to,美团) | NOOP | NOOP | √ | - | 完全重复的现有记忆，无需操作 |
| A14#1 | 我投了字节 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | NOOP; NOOP | NOOP; NOOP | √ | - | 已存在完全相同的记忆，无需操作; 已存在完全相同的记忆，无需操作 |
| U09#1 | 我投了腾讯 | (application_status,腾讯:submitted); (applied_to,腾讯) | NOOP; NOOP | NOOP; NOOP | √ | - | 候选事实与现有记忆完全重复; 候选事实与现有记忆完全重复 |
| U14#1 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复的现有记忆; 完全重复的现有记忆 |
| S-B1#0 | （合成）重复提及且置信更高：已投美团(0.9)，再投美团(0.95) | (applied_to,美团) | UPDATE,strengthen,('user', 'applied_to', '美团') | NOOP | × | LLM多出:NOOP×1; 规则有LLM缺:UPDATE:strengthen×1 | Duplicate of existing memory with same subject, predicate, and object; higher confidence does not constitute a contradiction or new information. |
| S-B1S#0 | （合成）技能重复强化：已会Python(0.8)，再说熟悉Python(0.85) | (uses,Python) | UPDATE,strengthen,('user', 'uses', 'Python') | UPDATE,strengthen,('user', 'uses', 'Python') | √ | - | 重复提及，合并强化置信度 |
| U08#1 | 我掌握 Python | (uses,Python) | UPDATE,strengthen,('user', 'uses', 'Python') | NOOP | × | LLM多出:NOOP×1; 规则有LLM缺:UPDATE:strengthen×1 | Same triple already exists with higher confidence, no change needed. |
| A01#1 | 字节跳动的流程结束了 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | √ | - | 应聘状态由submitted更新为ended，新事实取代旧状态。 |
| A03#1 | 蚂蚁的流程结束了 | (applied_to,蚂蚁集团); (application_status,蚂蚁集团:submitted) | UPDATE,supersede,('user', 'application_status', '蚂蚁集团:submitted'),('user', 'application_status', '蚂蚁集团:ended') | UPDATE,supersede,('user', 'application_status', '蚂蚁集团:submitted'),('user', 'application_status', '蚂蚁集团:ended') | √ | - | Candidate fact updates the application status of user for 蚂蚁集团 from 'submitted' to 'ended', superseding the prior status. |
| A06#1 | 收到快手的面试邀请 | (applied_to,快手); (application_status,快手:submitted) | UPDATE,supersede,('user', 'application_status', '快手:submitted'),('user', 'application_status', '快手:interviewing') | UPDATE,supersede,('user', 'application_status', '快手:submitted'),('user', 'application_status', '快手:interviewing') | √ | - | Application status for 快手 changed from submitted to interviewing, so the existing memory should be updated to reflect the new status. |
| A10#1 | 我现在在字节上班 | (works_at,美团) | UPDATE,supersede,('user', 'works_at', '美团'),('user', 'works_at', '字节跳动') | UPDATE,supersede,('user', 'works_at', '美团'),('user', 'works_at', '字节跳动') | √ | - | 新事实表明用户工作单位由美团变为字节跳动，存在冲突，以新事实为准，更新旧记忆。 |
| A11#1 | 我在字节跳动工作 | (works_at,网易) | UPDATE,supersede,('user', 'works_at', '网易'),('user', 'works_at', '字节跳动') | UPDATE,supersede,('user', 'works_at', '网易'),('user', 'works_at', '字节跳动') | √ | - | 现有记忆称用户在网易工作，候选事实称用户在字节跳动工作，二者矛盾。候选事实为最新信息，应更新原记忆为被取代状态，并记录新事实。 |
| A17#1 | 字节挂了 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | √ | - | Application status at ByteDance changed from submitted to ended; the new fact supersedes the old status. |
| A13#0 | 不想投字节了 | 无 | ADD,('user', 'withdrawn', '字节跳动') | ADD,('user', 'withdrawn', '字节跳动') | √ | - | 撤销意图（无对应记忆），留档 |
| W04#0 | 不想投腾讯了 | 无 | ADD,('user', 'withdrawn', '腾讯') | ADD,('user', 'withdrawn', '腾讯') | √ | - | 撤销意图（无对应记忆），留档 |
| W11#2 | 不想投京东了 | (withdrawn,京东) | ADD,('user', 'withdrawn', '京东') | ADD,('user', 'withdrawn', '京东') | √ | - | 撤销意图（无对应记忆），留档 |
| A02#1 | 取消阿里的申请 | (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted) | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user applied_to 阿里巴巴; 撤销：失效 user application_status 阿里巴巴:submitted; 撤销事实留档（审计可查） |
| A19#1 | 取消阿里的申请 | (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted); (applied_to,字节跳动); (application_status,字节跳动:submitted) | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user applied_to 阿里巴巴; 撤销：失效 user application_status 阿里巴巴:submitted; 撤销事实留档（审计可查） |
| D09#1 | 取消腾讯的申请 | (applied_to,腾讯); (application_status,腾讯:submitted) | DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | √ | - | 撤销：失效 user applied_to 腾讯; 撤销：失效 user application_status 腾讯:submitted; 撤销事实留档（审计可查） |
| M12#1 | 取消阿里的申请 | (application_status,阿里巴巴:submitted); (applied_to,阿里巴巴) | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user application_status 阿里巴巴:submitted; 撤销：失效 user applied_to 阿里巴巴; 撤销事实留档（审计可查） |
| S-C1M#0 | （合成）撤销命中两条：已投美团+已提交，再说取消美团申请 | (applied_to,美团); (application_status,美团:submitted) | DELETE,('user', 'applied_to', '美团'); DELETE,('user', 'application_status', '美团:submitted'); ADD,('user', 'withdrawn', '美团') | DELETE,('user', 'applied_to', '美团'); DELETE,('user', 'application_status', '美团:submitted'); ADD,('user', 'withdrawn', '美团') | √ | - | 撤销：失效 user applied_to 美团; 撤销：失效 user application_status 美团:submitted; 撤销事实留档（审计可查） |
| S-MIX#0 | （合成）混合批：新投快手+同时取消腾讯（腾讯在库） | (applied_to,腾讯); (application_status,腾讯:submitted) | ADD,('user', 'applied_to', '快手'); DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯'); ADD,('user', 'applied_to', '快手') | ≈ | 目标/事实错位（动作类型一致） | 撤销：失效 user applied_to 腾讯; 撤销：失效 user application_status 腾讯:submitted; 撤销事实留档（审计可查）; 新事实：用户申请了快手，与现有腾讯相关记忆不冲突，可同时成立。 |

## 汇总

- 动作序列完全一致：**41/44 = 93%**；多重集一致（含顺序差）：42/44
- LLM 异常回退（fallback_error）：0/44；结构性分支委托规则版（撤销/重复提及 UPDATE 定位）按试样统计见 llm_stats 字段
- 分层一致率见下表（合成-语义探针层 = 矩阵分支的最小合成试验）。

| 层 | 一致/试验 |
|---|---|
| 事实更新 | 4/5 |
| 冲突撤回 | 4/4 |
| 别名归一 | 24/24 |
| 合成-语义探针 | 4/6 |
| 多跳召回 | 4/4 |
| 时序衰减 | 1/1 |

## 分歧模式分布

```
  2  LLM多出:NOOP×1
  2  规则有LLM缺:UPDATE:strengthen×1
  1  目标/事实错位（动作类型一致）
```

## 分析

<!-- ANALYSIS_PLACEHOLDER -->
