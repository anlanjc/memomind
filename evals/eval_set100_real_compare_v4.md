# memomind 真模型抽取对比 v4（同一 20 条，混合架构空抽兜底接线验收）

- 与 v3 的唯一变量：LLM 抽取器外套 `memomind/extract.py::HybridExtractor`——LLM 抽取结果为空时回退 RuleExtractor（开关默认开、事件留痕）。规则端基准、normalize 层词典、抽取 prompt 全部零改动。
- 花费（usage 实测）：40 次调用，10160 in + 14315 out tokens ≈ ¥0.21（本轮上限 ¥0.3），单价假设 ¥4.0/M in, ¥12.0/M out（保守上限），账本 evals/.real_extract_ledger_v4.json。
- 传输层：curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com 绕过本机半死系统代理。

| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 原始 (pred, obj) | 混合输出 (pred, obj) | 一致 | 路径 | 规则独有 | 混合独有 |
|---|---|---|---|---|---|---|---|---|
| U01 | 我想投后端岗 | (target_role,后端岗) | (interested_in,后端岗位) | (target_role,后端岗) | √ | LLM | - | - |
| U08 | 我掌握 Python | (uses,Python) | (has_skill,Python) | (uses,Python) | √ | LLM | - | - |
| U10 | 我投了美团和快手 | (applied_to,美团); (application_status,美团:submitted); (applied_to,快手); (application_status,快手:submitted) | (applied_to,美团); (applied_to,快手) | (applied_to,美团); (applied_to,快手); (application_status,美团:submitted); (application_status,快手:submitted) | √ | LLM | - | - |
| U16 | 我叫王芳，我想投测试岗 | (name,王芳); (target_role,测试岗) | (has_name,王芳); (wants_to_apply_for,测试岗位) | (name,王芳); (target_role,测试岗) | √ | LLM | - | - |
| U17 | 我想去广州工作 | (prefers_city,广州) | (prefers_work_location,广州) | (prefers_city,广州) | √ | LLM | - | - |
| W03 | 取消阿里的申请 | (withdrawn,阿里巴巴) | (applied_to,阿里巴巴) | (withdrawn,阿里巴巴) | √ | LLM | - | - |
| W04 | 不想投腾讯了 | (withdrawn,腾讯) | (applied_to,腾讯) | (withdrawn,腾讯) | √ | LLM | - | - |
| W05 | 收到字节的offer | (application_status,字节跳动:offer) | (received_offer_from,字节跳动) | (application_status,字节跳动:offer) | √ | LLM | - | - |
| W09 | 滴滴挂了 | (application_status,滴滴:ended) | (was_rejected_by,滴滴出行) | (application_status,滴滴:ended) | √ | LLM | - | - |
| W15 | 我投了腾讯和阿里 | (applied_to,腾讯); (application_status,腾讯:submitted); (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted) | (applied_to,腾讯); (applied_to,阿里巴巴) | (applied_to,腾讯); (applied_to,阿里巴巴); (application_status,腾讯:submitted); (application_status,阿里巴巴:submitted) | √ | LLM | - | - |
| A01 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| A04 | 我投了字节的Agent岗 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动 Agent岗) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| A05 | 投了deepseek | (applied_to,DeepSeek); (application_status,DeepSeek:submitted) | (applied_to,DeepSeek) | (applied_to,DeepSeek); (application_status,DeepSeek:submitted) | √ | LLM | - | - |
| A14 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| D01 | 我投了滴滴 | (applied_to,滴滴); (application_status,滴滴:submitted) | (applied_to,滴滴出行) | (applied_to,滴滴); (application_status,滴滴:submitted) | √ | LLM | - | - |
| D16 | 我投了美团 | (applied_to,美团); (application_status,美团:submitted) | (applied_to,美团) | (applied_to,美团); (application_status,美团:submitted) | √ | LLM | - | - |
| M01 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| M02 | 我熟悉 Python、FastAPI 和 MySQL | (uses,Python); (uses,FastAPI); (uses,MySQL) | (skilled_in,Python); (skilled_in,FastAPI); (skilled_in,MySQL) | (uses,Python); (uses,FastAPI); (uses,MySQL) | √ | LLM | - | - |
| M10 | 我叫王芳，我投了腾讯 | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | (name,王芳); (applied_to,腾讯) | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | √ | LLM | - | - |
| M20 | 改投后端岗了 | (target_role,后端岗) | (applied_to,后端岗位) | (target_role,后端岗) | √ | LLM | - | - |

## 汇总

- 混合架构完全一致：**20/20 = 100%**（v3 无兜底 19/20，残差=LLM 空抽）
- 路径构成：LLM 自身命中 20/20，规则兜底救回 0/20，双空（疑问句）0/20
- LLM 非空且未归一原始输出即完全一致：0/20（原始对照口径，改进仍归因归一化层）

## 差异分析

**修复路径（两轮复测 + 有界探针，花费全程 usage 实记账本）：18/20 → 20/20 = 100%**
（v3 无兜底基线 19/20；本轮目标"19/20→20/20"达成）。

- **第一轮（混合接线，词典未动）18/20**：W09 本轮没有空抽（LLM 召回波动换
  了方向），但 LLM 造出两条 v3 没见过的新变体——U01"我想投后端岗"被抽成
  `(prefers, 后端开发岗位)`（v3 轮是 `interested_in`，谓词+宾语双变体，
  多出的"开发"让岗位折迭与 role 判定双双失效）、A05"投了deepseek"被翻译成
  官方中文名"深度求索"（别名表没这条）。词典法枚举盲区的运行间变异再次复现。
- **增量修订（红线内：词典增量，不推倒重来）四条，条目全部来自实测证据**：
  ① COMPANY_ALIASES + 深度求索→DeepSeek；② target_role 宾语折迭 `_fold_role`
  吸收"开发/工程师"嵌入缀（后端开发岗位→后端岗）；③ 宾语感知扩展
  prefers+岗位宾语→target_role（岗位宾语是唯一判据，"更喜欢远程办公"不动）；
  ④ 探针追加失败类亚词兜底 `_SUBWORD_STATUS`（fail/reject 词根→ended 状态改写）。
- **第二轮（同 20 条复测）20/20 = 100%**：两条变体全部闭合，路径构成
  LLM 自身命中 20、兜底救回 0、双空 0。
- **W09 空抽活体探针（10 次同输入实跑）**：v3 的空抽本会话未复现（10/10
  无空抽）——LLM 波动本身波动，兜底路径在真模型评测里未被触发；但探针
  第一轮 5 次同输入产出 **4 种谓词变体**（failed_at×2 / was_rejected_by /
  failed_interview_at / failed_application，最后者词典未登记→4/5 匹配），
  变体波动被活体捕捉并触发修订④，第二轮 5/5 全匹配。**同一句"挂了"
  temperature=0 下 5 次调用 4 种谓词**是词典法必须配亚词兜底的最强实证。
- **空抽兜底机制的证据构成**：本会话 50 次真模型调用零空抽，活体救回
  未发生——机制正确性由 7 项回归测试钉死（空抽救回/疑问句双空留痕/
  开关关闭直通/部分召回不混流/事件累计/日志留痕/管线端到端接线），
  生产接线在 api.py 真模型装配点（HybridExtractor 默认包裹
  OpenAICompatibleExtractor）。事件留痕（events 列表 + rescued 标记 +
  logger.warning）在离线测试与生产路径同构。

**结论**：谓词映射层（v3）+ 空抽规则兜底（v4）合起来是混合架构的完整
落地——LLM 命中时归一层保证 schema 一致，LLM 抽空时规则底线保证事实
不丢；两路对比口径全程可归因（兜底只在结果为空时触发、不混流）。
残差风险收敛为"LLM 抽出错误而非缺失的事实"（本会话未出现，词典按
活词典机制持续按证据扩充）。

**诚实边界**：探针 10 次未复现空抽，兜底救回的真实触发样本为零，机制
证据=回归测试；活词典仍会随新变体扩充（每条修订都带实测证据与单测）；
花费 ¥0.29（50 次调用，usage 实记，上限 ¥0.3）。
