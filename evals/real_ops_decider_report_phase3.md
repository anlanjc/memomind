# LLMOpsDecider 真模型决策对比（规则决策矩阵基准，MM-3）

- 口径：决策层单变量对比——抽取层冻结为 RuleExtractor，两路喂完全相同的候选事实与 active 记忆快照（来自 eval_set_100 复放的决策点）；判定基准=规则决策矩阵输出（mock 评测 100/100 的同一套确定性金标）。
- 抽样：全量决策点分层抽样 44 个试验（每模式 ≤6），模式分布见下；LLM=deepseek-v4-flash（与抽取对比同模型同传输层）。
- 花费（usage 实测）：88 次调用，28595 in + 14669 out tokens ≈ ¥0.29（上限 ¥1.0），账本 evals/.real_ops_ledger.json。
- 传输层：curl(schannel) + NO_PROXY=dashscope.aliyuncs.com。

| 用例 | 输入 | 现有记忆 | 规则矩阵动作 | LLM 动作 | 判定 | 分歧 | LLM 理由 |
|---|---|---|---|---|---|---|---|
| A09#0 | 字节挂了 | 无 | ADD,('user', 'application_status', '字节跳动:ended') | ADD,('user', 'application_status', '字节跳动:ended') | √ | - | 用户字节跳动申请状态为已结束，为全新事实，尚无相关记忆。 |
| A10#0 | 我现在在美团上班 | 无 | ADD,('user', 'works_at', '美团') | ADD,('user', 'works_at', '美团') | √ | - | 现有记忆为空，该事实为全新信息 |
| A11#0 | 我在网易工作 | 无 | ADD,('user', 'works_at', '网易') | ADD,('user', 'works_at', '网易') | √ | - | 现有记忆为空，该事实为新信息，直接添加。 |
| A12#0 | 收到蚂蚁的面试邀请 | 无 | ADD,('user', 'application_status', '蚂蚁集团:interviewing') | ADD,('user', 'application_status', '蚂蚁集团:interviewing') | √ | - | New high-confidence fact about user's application status with Ant Group. |
| A15#0 | 收到字节的offer | 无 | ADD,('user', 'application_status', '字节跳动:offer') | ADD,('user', 'application_status', '字节跳动:offer') | √ | - | New fact: user has an offer from ByteDance. |
| A18#0 | 我在华为工作 | 无 | ADD,('user', 'works_at', '华为') | ADD,('user', 'works_at', '华为') | √ | - | 用户工作单位信息为全新事实，且现有记忆为空，直接添加。 |
| A01#0 | 我投了字节 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 新增事实：用户申请了字节跳动; 新增事实：用户对字节跳动的申请状态为已提交 |
| A02#0 | 我投了阿里巴巴 | 无 | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 全新事实：用户申请了阿里巴巴; 全新事实：用户向阿里巴巴的申请状态为已提交 |
| A03#0 | 我投了蚂蚁 | 无 | ADD,('user', 'applied_to', '蚂蚁集团'); ADD,('user', 'application_status', '蚂蚁集团:submitted') | ADD,('user', 'applied_to', '蚂蚁集团'); ADD,('user', 'application_status', '蚂蚁集团:submitted') | √ | - | 无现有记忆，新增用户申请蚂蚁集团的事实; 无现有记忆，新增用户申请状态为已提交的事实 |
| A04#0 | 我投了字节的Agent岗 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | New fact: user applied to 字节跳动, not present in existing memories.; New fact: user's application to 字节跳动 is submitted, complementing the application record. |
| A05#0 | 投了deepseek | 无 | ADD,('user', 'applied_to', 'DeepSeek'); ADD,('user', 'application_status', 'DeepSeek:submitted') | ADD,('user', 'applied_to', 'DeepSeek'); ADD,('user', 'application_status', 'DeepSeek:submitted') | √ | - | 全新事实：用户已申请DeepSeek，现有记忆中无对应条目。; 全新事实：用户的DeepSeek申请状态为已提交，现有记忆中无对应条目。 |
| A06#0 | 我投了快手 | 无 | ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 用户申请快手的全新事实，现有记忆中无对应记录; 用户申请进度为已提交，是全新且有价值的状态事实 |
| M02#0 | 我熟悉 Python、FastAPI 和 MySQL | 无 | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | √ | - | 全新事实：用户使用Python; 全新事实：用户使用FastAPI; 全新事实：用户使用MySQL |
| M10#0 | 我叫王芳，我投了腾讯 | 无 | ADD,('user', 'name', '王芳'); ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted') | ADD,('user', 'name', '王芳'); ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted') | √ | - | 全新事实：用户姓名为王芳; 全新事实：用户申请了腾讯; 全新事实：用户对腾讯的申请状态为已提交 |
| U15#0 | 我熟悉 Python、FastAPI 和 MySQL | 无 | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | ADD,('user', 'uses', 'Python'); ADD,('user', 'uses', 'FastAPI'); ADD,('user', 'uses', 'MySQL') | √ | - | 全新事实，用户使用Python; 全新事实，用户使用FastAPI; 全新事实，用户使用MySQL |
| A08#0 | 我投了阿里和字节 | 无 | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted') | √ | - | 用户申请了阿里巴巴，属于全新事实; 阿里巴巴的申请状态为已提交，属于全新事实; 用户申请了字节跳动，属于全新事实; 字节跳动的申请状态为已提交，属于全新事实 |
| A19#0 | 我投了字节和阿里 | 无 | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '字节跳动'); ADD,('user', 'application_status', '字节跳动:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 用户申请了字节跳动，新事实; 字节跳动申请状态为已提交，新事实; 用户申请了阿里巴巴，新事实; 阿里巴巴申请状态为已提交，新事实 |
| M06#0 | 我投了腾讯和阿里 | 无 | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 新事实：用户申请了腾讯; 新事实：用户向腾讯的申请状态为已提交; 新事实：用户申请了阿里巴巴; 新事实：用户向阿里巴巴的申请状态为已提交 |
| U10#0 | 我投了美团和快手 | 无 | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 用户已申请美团，新事实; 美团申请状态为已提交，新事实; 用户已申请快手，新事实; 快手申请状态为已提交，新事实 |
| W06#0 | 我投了美团和快手 | 无 | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | ADD,('user', 'applied_to', '美团'); ADD,('user', 'application_status', '美团:submitted'); ADD,('user', 'applied_to', '快手'); ADD,('user', 'application_status', '快手:submitted') | √ | - | 全新事实：用户申请了美团; 全新事实：美团申请状态为已提交; 全新事实：用户申请了快手; 全新事实：快手申请状态为已提交 |
| W15#0 | 我投了腾讯和阿里 | 无 | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | ADD,('user', 'applied_to', '腾讯'); ADD,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'application_status', '阿里巴巴:submitted') | √ | - | 全新事实：用户申请了腾讯; 全新事实：腾讯申请状态为已提交; 全新事实：用户申请了阿里巴巴; 全新事实：阿里巴巴申请状态为已提交 |
| S-A0#0 | （合成）低置信丢弃：一条0.2置信的偏好 | 无 | NOOP | ADD,('user', 'prefers', '远程办公') | × | LLM多出:ADD×1; 规则有LLM缺:NOOP×1 | 没有现有记忆，该事实是全新的，尽管置信度较低，仍可添加以供参考。 |
| S-B2#0 | （合成）完全重复同置信：已投美团(0.9)，再投美团(0.9) | (applied_to,美团) | NOOP | NOOP | √ | - | 完全重复，跳过 |
| A14#1 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复，跳过; 完全重复，跳过 |
| U09#1 | 我投了腾讯 | (application_status,腾讯:submitted); (applied_to,腾讯) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复，跳过; 完全重复，跳过 |
| U14#1 | 我投了字节 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | NOOP; NOOP | NOOP; NOOP | √ | - | 完全重复，跳过; 完全重复，跳过 |
| S-B1#0 | （合成）重复提及且置信更高：已投美团(0.9)，再投美团(0.95) | (applied_to,美团) | UPDATE,strengthen,('user', 'applied_to', '美团') | UPDATE,strengthen,('user', 'applied_to', '美团') | √ | - | 重复提及，合并强化置信度 |
| S-B1S#0 | （合成）技能重复强化：已会Python(0.8)，再说熟悉Python(0.85) | (uses,Python) | UPDATE,strengthen,('user', 'uses', 'Python') | UPDATE,strengthen,('user', 'uses', 'Python') | √ | - | 重复提及，合并强化置信度 |
| U08#1 | 我掌握 Python | (uses,Python) | UPDATE,strengthen,('user', 'uses', 'Python') | UPDATE,strengthen,('user', 'uses', 'Python') | √ | - | 重复提及，合并强化置信度 |
| A01#1 | 字节跳动的流程结束了 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | √ | - | 候选事实将申请状态从 submitted 更新为 ended，因此覆盖原有状态记忆，同时保留 applied_to 记录。 |
| A03#1 | 蚂蚁的流程结束了 | (applied_to,蚂蚁集团); (application_status,蚂蚁集团:submitted) | UPDATE,supersede,('user', 'application_status', '蚂蚁集团:submitted'),('user', 'application_status', '蚂蚁集团:ended') | UPDATE,supersede,('user', 'application_status', '蚂蚁集团:submitted'),('user', 'application_status', '蚂蚁集团:ended') | √ | - | 候选事实将申请状态从 submitted 更新为 ended，新事实取代旧状态记忆。 |
| A06#1 | 收到快手的面试邀请 | (applied_to,快手); (application_status,快手:submitted) | UPDATE,supersede,('user', 'application_status', '快手:submitted'),('user', 'application_status', '快手:interviewing') | UPDATE,supersede,('user', 'application_status', '快手:submitted'),('user', 'application_status', '快手:interviewing') | √ | - | User's 快手 application status changed from submitted to interviewing; the new status supersedes the existing submitted status. |
| A10#1 | 我现在在字节上班 | (works_at,美团) | UPDATE,supersede,('user', 'works_at', '美团'),('user', 'works_at', '字节跳动') | UPDATE,supersede,('user', 'works_at', '美团'),('user', 'works_at', '字节跳动') | √ | - | New fact contradicts existing memory (works_at 字节跳动 vs 美团). The new fact is more recent and takes precedence, so the existing memory is superseded. |
| A11#1 | 我在字节跳动工作 | (works_at,网易) | UPDATE,supersede,('user', 'works_at', '网易'),('user', 'works_at', '字节跳动') | UPDATE,supersede,('user', 'works_at', '网易'),('user', 'works_at', '字节跳动') | √ | - | New fact indicates user now works at ByteDance, contradicting existing memory of NetEase. Since the new fact has equal confidence and is more recent, update the memory to reflect the change, marking the old one superseded. |
| A17#1 | 字节挂了 | (application_status,字节跳动:submitted); (applied_to,字节跳动) | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | UPDATE,supersede,('user', 'application_status', '字节跳动:submitted'),('user', 'application_status', '字节跳动:ended') | √ | - | 候选事实将申请状态从submitted更新为ended，新事实生效，旧状态被取代。 |
| A13#0 | 不想投字节了 | 无 | ADD,('user', 'withdrawn', '字节跳动') | ADD,('user', 'withdrawn', '字节跳动') | √ | - | 撤销意图（无对应记忆），留档 |
| W04#0 | 不想投腾讯了 | 无 | ADD,('user', 'withdrawn', '腾讯') | ADD,('user', 'withdrawn', '腾讯') | √ | - | 撤销意图（无对应记忆），留档 |
| W11#2 | 不想投京东了 | (withdrawn,京东) | ADD,('user', 'withdrawn', '京东') | ADD,('user', 'withdrawn', '京东') | √ | - | 撤销意图（无对应记忆），留档 |
| A02#1 | 取消阿里的申请 | (application_status,阿里巴巴:submitted); (applied_to,阿里巴巴) | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user application_status 阿里巴巴:submitted; 撤销：失效 user applied_to 阿里巴巴; 撤销事实留档（审计可查） |
| A19#1 | 取消阿里的申请 | (application_status,阿里巴巴:submitted); (applied_to,字节跳动); (applied_to,阿里巴巴); (application_status,字节跳动:submitted) | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'application_status', '阿里巴巴:submitted'); DELETE,('user', 'applied_to', '阿里巴巴'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user application_status 阿里巴巴:submitted; 撤销：失效 user applied_to 阿里巴巴; 撤销事实留档（审计可查） |
| D09#1 | 取消腾讯的申请 | (application_status,腾讯:submitted); (applied_to,腾讯) | DELETE,('user', 'application_status', '腾讯:submitted'); DELETE,('user', 'applied_to', '腾讯'); ADD,('user', 'withdrawn', '腾讯') | DELETE,('user', 'application_status', '腾讯:submitted'); DELETE,('user', 'applied_to', '腾讯'); ADD,('user', 'withdrawn', '腾讯') | √ | - | 撤销：失效 user application_status 腾讯:submitted; 撤销：失效 user applied_to 腾讯; 撤销事实留档（审计可查） |
| M12#1 | 取消阿里的申请 | (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted) | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | DELETE,('user', 'applied_to', '阿里巴巴'); DELETE,('user', 'application_status', '阿里巴巴:submitted'); ADD,('user', 'withdrawn', '阿里巴巴') | √ | - | 撤销：失效 user applied_to 阿里巴巴; 撤销：失效 user application_status 阿里巴巴:submitted; 撤销事实留档（审计可查） |
| S-C1M#0 | （合成）撤销命中两条：已投美团+已提交，再说取消美团申请 | (applied_to,美团); (application_status,美团:submitted) | DELETE,('user', 'applied_to', '美团'); DELETE,('user', 'application_status', '美团:submitted'); ADD,('user', 'withdrawn', '美团') | DELETE,('user', 'applied_to', '美团'); DELETE,('user', 'application_status', '美团:submitted'); ADD,('user', 'withdrawn', '美团') | √ | - | 撤销：失效 user applied_to 美团; 撤销：失效 user application_status 美团:submitted; 撤销事实留档（审计可查） |
| S-MIX#0 | （合成）混合批：新投快手+同时取消腾讯（腾讯在库） | (applied_to,腾讯); (application_status,腾讯:submitted) | ADD,('user', 'applied_to', '快手'); DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | ADD,('user', 'applied_to', '快手'); DELETE,('user', 'applied_to', '腾讯'); DELETE,('user', 'application_status', '腾讯:submitted'); ADD,('user', 'withdrawn', '腾讯') | √ | - | 用户申请快手是全新事实，与现有腾讯申请记录不冲突; 撤销：失效 user applied_to 腾讯; 撤销：失效 user application_status 腾讯:submitted; 撤销事实留档（审计可查） |

## 汇总

- 动作序列完全一致：**43/44 = 98%**；多重集一致（含顺序差）：43/44
- LLM 异常回退（fallback_error）：0/44；结构性分支委托规则版（撤销/重复提及 UPDATE 定位）按试样统计见 llm_stats 字段
- 分层一致率见下表（合成-语义探针层 = 矩阵分支的最小合成试验）。

| 层 | 一致/试验 |
|---|---|
| 事实更新 | 5/5 |
| 冲突撤回 | 4/4 |
| 别名归一 | 24/24 |
| 合成-语义探针 | 5/6 |
| 多跳召回 | 4/4 |
| 时序衰减 | 1/1 |

## 分歧模式分布

```
  1  LLM多出:ADD×1
  1  规则有LLM缺:NOOP×1
```

## 分析

<!-- ANALYSIS_PLACEHOLDER -->
