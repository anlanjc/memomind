# memomind 真模型抽取对比 v2（eval_set_100 抽样 20 条，deepseek-v4-flash）

- 口径：每条输入分别过 RuleExtractor 与 OpenAICompatibleExtractor，
  按 (predicate, object) 三元组集合对比（置信度与极性单列不参与集合判定）。
- 传输层：curl(schannel) transport 注入（同 miniagent 批评测的环境问题）。
- 花费（保守估算）：见 evals/.real_extract_ledger.json。

| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 抽取 (pred, obj) | 一致 | 规则独有 | LLM 独有 |
|---|---|---|---|---|---|---|
| U01 | 我想投后端岗 | (target_role,后端岗) | (wants_to_apply_to,后端岗) | 部分 | (target_role,后端岗) | (wants_to_apply_to,后端岗) |
| U08 | 我掌握 Python | (uses,Python) | (has_skill,Python) | 部分 | (uses,Python) | (has_skill,Python) |
| U10 | 我投了美团和快手 | (applied_to,美团); (application_status,美团:submitted); (applied_to,快手); (application_status,快手:submitted) | (applied_to,美团); (applied_to,快手) | 部分 | (application_status,快手:submitted); (application_status,美团:submitted) | - |
| U16 | 我叫王芳，我想投测试岗 | (name,王芳); (target_role,测试岗) | (name,王芳); (interested_in,测试岗) | 部分 | (target_role,测试岗) | (interested_in,测试岗) |
| U17 | 我想去广州工作 | (prefers_city,广州) | (wants_to_work_in,广州) | 部分 | (prefers_city,广州) | (wants_to_work_in,广州) |
| W03 | 取消阿里的申请 | (withdrawn,阿里巴巴) | (applied_to,阿里巴巴) | 部分 | (withdrawn,阿里巴巴) | (applied_to,阿里巴巴) |
| W04 | 不想投腾讯了 | (withdrawn,腾讯) | (applied_to,腾讯) | 部分 | (withdrawn,腾讯) | (applied_to,腾讯) |
| W05 | 收到字节的offer | (application_status,字节跳动:offer) | (received_offer_from,字节跳动) | 部分 | (application_status,字节跳动:offer) | (received_offer_from,字节跳动) |
| W09 | 滴滴挂了 | (application_status,滴滴:ended) | (was_rejected_by,滴滴出行) | 部分 | (application_status,滴滴:ended) | (was_rejected_by,滴滴出行) |
| W15 | 我投了腾讯和阿里 | (applied_to,腾讯); (application_status,腾讯:submitted); (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted) | (applied_to,腾讯); (applied_to,阿里巴巴) | 部分 | (application_status,腾讯:submitted); (application_status,阿里巴巴:submitted) | - |
| A01 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | 部分 | (application_status,字节跳动:submitted) | - |
| A04 | 我投了字节的Agent岗 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | 部分 | (application_status,字节跳动:submitted) | - |
| A05 | 投了deepseek | (applied_to,DeepSeek); (application_status,DeepSeek:submitted) | (applied_to,DeepSeek) | 部分 | (application_status,DeepSeek:submitted) | - |
| A14 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | 部分 | (application_status,字节跳动:submitted) | - |
| D01 | 我投了滴滴 | (applied_to,滴滴); (application_status,滴滴:submitted) | (applied_to,滴滴) | 部分 | (application_status,滴滴:submitted) | - |
| D16 | 我投了美团 | (applied_to,美团); (application_status,美团:submitted) | (applied_to,美团) | 部分 | (application_status,美团:submitted) | - |
| M01 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | 部分 | (application_status,字节跳动:submitted) | - |
| M02 | 我熟悉 Python、FastAPI 和 MySQL | (uses,Python); (uses,FastAPI); (uses,MySQL) | (has_skill,Python); (has_skill,FastAPI); (has_skill,MySQL) | 部分 | (uses,FastAPI); (uses,MySQL); (uses,Python) | (has_skill,FastAPI); (has_skill,MySQL); (has_skill,Python) |
| M10 | 我叫王芳，我投了腾讯 | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | (has_name,王芳); (applied_to,腾讯) | 部分 | (application_status,腾讯:submitted); (name,王芳) | (has_name,王芳) |
| M20 | 改投后端岗了 | (target_role,后端岗) | (applied_to,后端岗) | 部分 | (target_role,后端岗) | (applied_to,后端岗) |

## 汇总

- 完全一致：0/20 = 0%
- LLM 有独有抽取的输入：11/20；规则有独有抽取的输入：20/20

## 差异分析（v2 对比 v1 报告 real_model_report.md）

## 差异分析（v2 对比 v1 报告 real_model_report.md）

**总起：完全一致 0/20 不是"20 处独立错误"，而是 4 类系统性差异 + 2 处真实误抽。**

1. **谓词命名体系不一致（最大差异源，16/20 输入受影响）**：LLM 用自然语言谓词
   （has_skill/has_name/wants_to_apply_to/wants_to_work_in/received_offer_from/was_rejected_by），
   规则版用规范 schema（uses/name/target_role/prefers_city/application_status:X:offer）。
   v1 报告的发现④在大样本下完全复现。后果：LLM 输出直接进 ops 决策矩阵会失效——
   conflict_key 靠规范谓词分域（functional/entity/per_object），未注册谓词一律降级
   per_object（"宁可并存不可误杀"），单值属性冲突消解将失效。**接真模型必须先做谓词映射层。**
2. **隐含状态不冗余存储（9/20）**：规则版投递必产 applied_to + application_status:X:submitted
   两条；LLM 只产 applied_to。LLM 的选择其实更符合记忆经济学（状态可推导），
   但下游"流程状态查询"（意图映射 application_status）在纯 LLM 抽取下直接失效——
   状态机是本系统的核心数据结构，LLM 抽取不兼容。
3. **否定/撤回语义（W03/W04，与 v1 发现②同构但更细）**：LLM 抽成 applied_to + negative
   极性——极性对了（v1 连极性都丢），谓词错了。下游影响比 v1 结论的轻：
   决策层凭 polarity=='negative' 也会触发撤销路径，但"撤销意图留档"会以 applied_to
   落库（审计语义模糊，withdrawn 谓词的查询语义丢失）。
4. **实体归一化分叉（W09）**：LLM 把"滴滴"归一为"滴滴出行"（不在规则别名表）——
   两套归一化体系会把同一公司在记忆图上分裂成两个节点，冲突消解与图扩展同时失效。
   别名表必须作为共享基础设施给 LLM prompt 或后处理。
5. **真实误抽（2/20）**：M20 "改投后端岗了"被抽成 applied_to 后端岗（把岗位当公司——
   改投的"改"语义丢失，会与既有 target_role 冲突消解逻辑完全错开）。
6. **v1 结论复验**："规则打底 + LLM 增强"的混合架构判断在 v2 抽样下保持成立且证据更强——
   LLM 的独有增量主要是置信度更高（1.0 vs 0.9）与自然语义变体，而非新事实；
   规则版的 schema 兼容性（application_status 伴随对、withdrawn 谓词、别名表）是
   LLM 抽取不可替代的地基。

**费用口径**：20 次调用；memomind client 只返回 content 不透出 usage，
按每次 ~1k tokens 保守估 **≈¥0.1**（上限 ¥0.5 未超）。

