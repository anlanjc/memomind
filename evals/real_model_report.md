# memomind 真模型抽取 vs 规则抽取（deepseek-v4-flash）

| 输入 | 规则抽取 | LLM 抽取 | LLM 独有 |
|---|---|---|---|
| 我叫李雷，主要想投 Agent 开发方向的实习 | [('name', '李雷'), ('target_role', 'Agent开发')] | [('has_name', '李雷'), ('interested_in', 'Agent开发方向的实习')] | {('has_name', '李雷'), ('interested_in', 'Agent开发方向的实习')} |
| 上周投了字节跳动的数据分析师，还在流程中 | [('applied_to', '字节跳动的数据分析师'), ('application_status', '字节跳动的数据分析师:submitted')] | [('applied_to', '字节跳动数据分析师')] | {('applied_to', '字节跳动数据分析师')} |
| 我不想投阿里了，太远了 | [('withdrawn', '阿里巴巴')] | [('applied_to', '阿里巴巴')] | {('applied_to', '阿里巴巴')} |
| 我更喜欢远程办公，最好杭州或者上海 | [('prefers', '远程办公')] | [('prefers', '远程办公'), ('prefers_location', '杭州'), ('prefers_location', '上海')] | {('prefers_location', '杭州'), ('prefers_location', '上海')} |
| 字节跳动的流程结束了，没过一面 | [('application_status', '字节跳动:ended')] | [('applied_to', '字节跳动'), ('failed_interview_at', '字节跳动')] | {('failed_interview_at', '字节跳动'), ('applied_to', '字节跳动')} |
| 我掌握 Python 和 LangGraph，用过 MySQL | [('uses', 'Python'), ('uses', 'LangGraph')] | [('has_skill', 'Python'), ('has_skill', 'LangGraph'), ('has_skill', 'MySQL')] | {('has_skill', 'LangGraph'), ('has_skill', 'Python'), ('has_skill', 'MySQL')} |
| 今天天气怎么样？ | [] | [] | set() |

LLM 相对规则有增量的输入数：6/7

## 结论（面试叙事）

1. **LLM 抽取的增量是语义级的**：`failed_interview_at`（"没过一面"）、`prefers_location`（杭州/上海）——规则正则覆盖不了的意图。
2. **LLM 抽取也会丢关键语义**："我不想投阿里了"被抽成 `applied_to 阿里`（规则版正确抽出 withdrawn + 负向极性）——**撤回/否定语义是 LLM 抽取的典型盲区**。
3. **架构结论：规则打底 + LLM 增强是正确架构**——规则版保证确定性底线（撤回/结构化状态），LLM 版补充语义增量（LLMOpsDecider 异常回退规则版的机制正是为此设计）。
4. 谓词命名不一致（has_name vs name、interested_in vs target_role）——接真模型需要一层谓词归一映射（已知扩展项）。
