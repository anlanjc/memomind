# LLMOpsDecider 真模型决策对比 phase1（原始行为存档，MM-3）

- 本档为 phase1（LLMOpsDecider 原始行为：整批交 LLM、无结构分支委托）的rows 重建报告——当时报告生成崩在模板行（bug 已修），数据完好在 rows JSON。
- 汇总：完全一致 34/44 = 77%；多重集一致 34/44；分歧模式见终版报告分析节。

| 用例 | 输入 | 规则矩阵动作 | LLM 动作 | 判定 | 分歧 |
|---|---|---|---|---|---|
| A09#0 | 字节挂了 | ADD,['user', 'application_status', '字节跳动:ended'] | ADD,['user', 'application_status', '字节跳动:ended'] | √ | - |
| A10#0 | 我现在在美团上班 | ADD,['user', 'works_at', '美团'] | ADD,['user', 'works_at', '美团'] | √ | - |
| A11#0 | 我在网易工作 | ADD,['user', 'works_at', '网易'] | ADD,['user', 'works_at', '网易'] | √ | - |
| A12#0 | 收到蚂蚁的面试邀请 | ADD,['user', 'application_status', '蚂蚁集团:interviewing'] | ADD,['user', 'application_status', '蚂蚁集团:interviewing'] | √ | - |
| A15#0 | 收到字节的offer | ADD,['user', 'application_status', '字节跳动:offer'] | ADD,['user', 'application_status', '字节跳动:offer'] | √ | - |
| A18#0 | 我在华为工作 | ADD,['user', 'works_at', '华为'] | ADD,['user', 'works_at', '华为'] | √ | - |
| A01#0 | 我投了字节 | ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted'] | ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted'] | √ | - |
| A02#0 | 我投了阿里巴巴 | ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | √ | - |
| A03#0 | 我投了蚂蚁 | ADD,['user', 'applied_to', '蚂蚁集团']; ADD,['user', 'application_status', '蚂蚁集团:submitted'] | ADD,['user', 'applied_to', '蚂蚁集团']; ADD,['user', 'application_status', '蚂蚁集团:submitted'] | √ | - |
| A04#0 | 我投了字节的Agent岗 | ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted'] | ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted'] | √ | - |
| A05#0 | 投了deepseek | ADD,['user', 'applied_to', 'DeepSeek']; ADD,['user', 'application_status', 'DeepSeek:submitted'] | ADD,['user', 'applied_to', 'DeepSeek']; ADD,['user', 'application_status', 'DeepSeek:submitted'] | √ | - |
| A06#0 | 我投了快手 | ADD,['user', 'applied_to', '快手']; ADD,['user', 'application_status', '快手:submitted'] | ADD,['user', 'applied_to', '快手']; ADD,['user', 'application_status', '快手:submitted'] | √ | - |
| M02#0 | 我熟悉 Python、FastAPI 和 MySQL | ADD,['user', 'uses', 'Python']; ADD,['user', 'uses', 'FastAPI']; ADD,['user', 'uses', 'MySQL'] | ADD,['user', 'uses', 'Python']; ADD,['user', 'uses', 'FastAPI']; ADD,['user', 'uses', 'MySQL'] | √ | - |
| M10#0 | 我叫王芳，我投了腾讯 | ADD,['user', 'name', '王芳']; ADD,['user', 'applied_to', '腾讯']; ADD,['user', 'application_status', '腾讯:submitted'] | ADD,['user', 'name', '王芳']; ADD,['user', 'applied_to', '腾讯']; ADD,['user', 'application_status', '腾讯:submitted'] | √ | - |
| U15#0 | 我熟悉 Python、FastAPI 和 MySQL | ADD,['user', 'uses', 'Python']; ADD,['user', 'uses', 'FastAPI']; ADD,['user', 'uses', 'MySQL'] | ADD,['user', 'uses', 'Python']; ADD,['user', 'uses', 'FastAPI']; ADD,['user', 'uses', 'MySQL'] | √ | - |
| A08#0 | 我投了阿里和字节 | ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted']; ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted'] | ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted']; ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted'] | √ | - |
| A19#0 | 我投了字节和阿里 | ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted']; ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | ADD,['user', 'applied_to', '字节跳动']; ADD,['user', 'application_status', '字节跳动:submitted']; ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | √ | - |
| M06#0 | 我投了腾讯和阿里 | ADD,['user', 'applied_to', '腾讯']; ADD,['user', 'application_status', '腾讯:submitted']; ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | ADD,['user', 'applied_to', '腾讯']; ADD,['user', 'application_status', '腾讯:submitted']; ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | √ | - |
| U10#0 | 我投了美团和快手 | ADD,['user', 'applied_to', '美团']; ADD,['user', 'application_status', '美团:submitted']; ADD,['user', 'applied_to', '快手']; ADD,['user', 'application_status', '快手:submitted'] | ADD,['user', 'applied_to', '美团']; ADD,['user', 'application_status', '美团:submitted']; ADD,['user', 'applied_to', '快手']; ADD,['user', 'application_status', '快手:submitted'] | √ | - |
| W06#0 | 我投了美团和快手 | ADD,['user', 'applied_to', '美团']; ADD,['user', 'application_status', '美团:submitted']; ADD,['user', 'applied_to', '快手']; ADD,['user', 'application_status', '快手:submitted'] | ADD,['user', 'applied_to', '美团']; ADD,['user', 'application_status', '美团:submitted']; ADD,['user', 'applied_to', '快手']; ADD,['user', 'application_status', '快手:submitted'] | √ | - |
| W15#0 | 我投了腾讯和阿里 | ADD,['user', 'applied_to', '腾讯']; ADD,['user', 'application_status', '腾讯:submitted']; ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | ADD,['user', 'applied_to', '腾讯']; ADD,['user', 'application_status', '腾讯:submitted']; ADD,['user', 'applied_to', '阿里巴巴']; ADD,['user', 'application_status', '阿里巴巴:submitted'] | √ | - |
| S-A0#0 | （合成）低置信丢弃：一条0.2置信的偏好 | NOOP | NOOP | √ | - |
| S-B2#0 | （合成）完全重复同置信：已投美团(0.9)，再投美团(0.9) | NOOP | NOOP | √ | - |
| A14#1 | 我投了字节 | NOOP; NOOP | NOOP; NOOP | √ | - |
| U09#1 | 我投了腾讯 | NOOP; NOOP | NOOP; NOOP | √ | - |
| U14#1 | 我投了字节 | NOOP; NOOP | NOOP; NOOP | √ | - |
| S-B1#0 | （合成）重复提及且置信更高：已投美团(0.9)，再投美团(0.95) | UPDATE,strengthen,['user', 'applied_to', '美团'] | UPDATE,supersede,['user', 'applied_to', '美团'],['user', 'applied_to', '美团'] | × | 规则有LLM缺:UPDATE:strengthen×1; LLM多出:UPDATE:supersede×1 |
| S-B1S#0 | （合成）技能重复强化：已会Python(0.8)，再说熟悉Python(0.85) | UPDATE,strengthen,['user', 'uses', 'Python'] | NOOP | × | LLM多出:NOOP×1; 规则有LLM缺:UPDATE:strengthen×1 |
| U08#1 | 我掌握 Python | UPDATE,strengthen,['user', 'uses', 'Python'] | NOOP | × | LLM多出:NOOP×1; 规则有LLM缺:UPDATE:strengthen×1 |
| A01#1 | 字节跳动的流程结束了 | UPDATE,supersede,['user', 'application_status', '字节跳动:submitted'],['user', 'application_status', '字节跳动:ended'] | UPDATE,supersede,['user', 'application_status', '字节跳动:submitted'],['user', 'application_status', '字节跳动:ended'] | √ | - |
| A03#1 | 蚂蚁的流程结束了 | UPDATE,supersede,['user', 'application_status', '蚂蚁集团:submitted'],['user', 'application_status', '蚂蚁集团:ended'] | UPDATE,supersede,['user', 'application_status', '蚂蚁集团:submitted'],['user', 'application_status', '蚂蚁集团:ended'] | √ | - |
| A06#1 | 收到快手的面试邀请 | UPDATE,supersede,['user', 'application_status', '快手:submitted'],['user', 'application_status', '快手:interviewing'] | UPDATE,supersede,['user', 'application_status', '快手:submitted'],['user', 'application_status', '快手:interviewing'] | √ | - |
| A10#1 | 我现在在字节上班 | UPDATE,supersede,['user', 'works_at', '美团'],['user', 'works_at', '字节跳动'] | UPDATE,supersede,['user', 'works_at', '美团'],['user', 'works_at', '字节跳动'] | √ | - |
| A11#1 | 我在字节跳动工作 | UPDATE,supersede,['user', 'works_at', '网易'],['user', 'works_at', '字节跳动'] | UPDATE,supersede,['user', 'works_at', '网易'],['user', 'works_at', '字节跳动'] | √ | - |
| A17#1 | 字节挂了 | UPDATE,supersede,['user', 'application_status', '字节跳动:submitted'],['user', 'application_status', '字节跳动:ended'] | UPDATE,supersede,['user', 'application_status', '字节跳动:submitted'],['user', 'application_status', '字节跳动:ended'] | √ | - |
| A13#0 | 不想投字节了 | ADD,['user', 'withdrawn', '字节跳动'] | ADD,['user', 'withdrawn', '字节跳动'] | √ | - |
| W04#0 | 不想投腾讯了 | ADD,['user', 'withdrawn', '腾讯'] | ADD,['user', 'withdrawn', '腾讯'] | √ | - |
| W11#2 | 不想投京东了 | ADD,['user', 'withdrawn', '京东'] | NOOP | × | 规则有LLM缺:ADD×1; LLM多出:NOOP×1 |
| A02#1 | 取消阿里的申请 | DELETE,['user', 'applied_to', '阿里巴巴']; DELETE,['user', 'application_status', '阿里巴巴:submitted']; ADD,['user', 'withdrawn', '阿里巴巴'] | UPDATE,supersede,['user', 'application_status', '阿里巴巴:submitted'],['user', 'withdrawn', '阿里巴巴'] | × | 规则有LLM缺:ADD×1; 规则有LLM缺:DELETE×2; LLM多出:UPDATE:supersede×1 |
| A19#1 | 取消阿里的申请 | DELETE,['user', 'applied_to', '阿里巴巴']; DELETE,['user', 'application_status', '阿里巴巴:submitted']; ADD,['user', 'withdrawn', '阿里巴巴'] | NOOP | × | 规则有LLM缺:ADD×1; 规则有LLM缺:DELETE×2; LLM多出:NOOP×1 |
| D09#1 | 取消腾讯的申请 | DELETE,['user', 'application_status', '腾讯:submitted']; DELETE,['user', 'applied_to', '腾讯']; ADD,['user', 'withdrawn', '腾讯'] | UPDATE,supersede,['user', 'application_status', '腾讯:submitted'],['user', 'withdrawn', '腾讯'] | × | 规则有LLM缺:ADD×1; 规则有LLM缺:DELETE×2; LLM多出:UPDATE:supersede×1 |
| M12#1 | 取消阿里的申请 | DELETE,['user', 'applied_to', '阿里巴巴']; DELETE,['user', 'application_status', '阿里巴巴:submitted']; ADD,['user', 'withdrawn', '阿里巴巴'] | UPDATE,supersede,['user', 'application_status', '阿里巴巴:submitted'],['user', 'withdrawn', '阿里巴巴'] | × | 规则有LLM缺:ADD×1; 规则有LLM缺:DELETE×2; LLM多出:UPDATE:supersede×1 |
| S-C1M#0 | （合成）撤销命中两条：已投美团+已提交，再说取消美团申请 | DELETE,['user', 'applied_to', '美团']; DELETE,['user', 'application_status', '美团:submitted']; ADD,['user', 'withdrawn', '美团'] | UPDATE,supersede,['user', 'application_status', '美团:submitted'],['user', 'withdrawn', '美团'] | × | 规则有LLM缺:ADD×1; 规则有LLM缺:DELETE×2; LLM多出:UPDATE:supersede×1 |
| S-MIX#0 | （合成）混合批：新投快手+同时取消腾讯（腾讯在库） | ADD,['user', 'applied_to', '快手']; DELETE,['user', 'applied_to', '腾讯']; DELETE,['user', 'application_status', '腾讯:submitted']; ADD,['user', 'withdrawn', '腾讯'] | ADD,['user', 'applied_to', '快手']; UPDATE,supersede,['user', 'application_status', '腾讯:submitted'],['user', 'withdrawn', '腾讯'] | × | 规则有LLM缺:ADD×1; 规则有LLM缺:DELETE×2; LLM多出:UPDATE:supersede×1 |