# memomind 真模型抽取对比 v4（同一 20 条，混合架构空抽兜底接线验收）

- 与 v3 的唯一变量：LLM 抽取器外套 `memomind/extract.py::HybridExtractor`——LLM 抽取结果为空时回退 RuleExtractor（开关默认开、事件留痕）。规则端基准、normalize 层词典、抽取 prompt 全部零改动。
- 花费（usage 实测）：20 次调用，5080 in + 8239 out tokens ≈ ¥0.12（本轮上限 ¥0.3），单价假设 ¥4.0/M in, ¥12.0/M out（保守上限），账本 evals/.real_extract_ledger_v4.json。
- 传输层：curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com 绕过本机半死系统代理。

| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 原始 (pred, obj) | 混合输出 (pred, obj) | 一致 | 路径 | 规则独有 | 混合独有 |
|---|---|---|---|---|---|---|---|---|
| U01 | 我想投后端岗 | (target_role,后端岗) | (prefers,后端开发岗位) | (prefers,后端开发岗位) | 部分 | LLM | (target_role,后端岗) | (prefers,后端开发岗位) |
| U08 | 我掌握 Python | (uses,Python) | (has_skill,Python) | (uses,Python) | √ | LLM | - | - |
| U10 | 我投了美团和快手 | (applied_to,美团); (application_status,美团:submitted); (applied_to,快手); (application_status,快手:submitted) | (applied_to,美团); (applied_to,快手) | (applied_to,美团); (applied_to,快手); (application_status,美团:submitted); (application_status,快手:submitted) | √ | LLM | - | - |
| U16 | 我叫王芳，我想投测试岗 | (name,王芳); (target_role,测试岗) | (name,王芳); (wants_apply,测试岗) | (name,王芳); (target_role,测试岗) | √ | LLM | - | - |
| U17 | 我想去广州工作 | (prefers_city,广州) | (wants_to_work_in,广州) | (prefers_city,广州) | √ | LLM | - | - |
| W03 | 取消阿里的申请 | (withdrawn,阿里巴巴) | (applied_to,阿里巴巴) | (withdrawn,阿里巴巴) | √ | LLM | - | - |
| W04 | 不想投腾讯了 | (withdrawn,腾讯) | (applied_to,腾讯) | (withdrawn,腾讯) | √ | LLM | - | - |
| W05 | 收到字节的offer | (application_status,字节跳动:offer) | (received_offer_from,字节跳动) | (application_status,字节跳动:offer) | √ | LLM | - | - |
| W09 | 滴滴挂了 | (application_status,滴滴:ended) | (failed_at,滴滴出行) | (application_status,滴滴:ended) | √ | LLM | - | - |
| W15 | 我投了腾讯和阿里 | (applied_to,腾讯); (application_status,腾讯:submitted); (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted) | (applied_to,腾讯); (applied_to,阿里巴巴) | (applied_to,腾讯); (applied_to,阿里巴巴); (application_status,腾讯:submitted); (application_status,阿里巴巴:submitted) | √ | LLM | - | - |
| A01 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| A04 | 我投了字节的Agent岗 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动的Agent岗) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| A05 | 投了deepseek | (applied_to,DeepSeek); (application_status,DeepSeek:submitted) | (applied_to,深度求索) | (applied_to,深度求索); (application_status,深度求索:submitted) | 部分 | LLM | (application_status,DeepSeek:submitted); (applied_to,DeepSeek) | (application_status,深度求索:submitted); (applied_to,深度求索) |
| A14 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| D01 | 我投了滴滴 | (applied_to,滴滴); (application_status,滴滴:submitted) | (applied_to,滴滴出行) | (applied_to,滴滴); (application_status,滴滴:submitted) | √ | LLM | - | - |
| D16 | 我投了美团 | (applied_to,美团); (application_status,美团:submitted) | (applied_to,美团) | (applied_to,美团); (application_status,美团:submitted) | √ | LLM | - | - |
| M01 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | LLM | - | - |
| M02 | 我熟悉 Python、FastAPI 和 MySQL | (uses,Python); (uses,FastAPI); (uses,MySQL) | (has_skill,Python); (has_skill,FastAPI); (has_skill,MySQL) | (uses,Python); (uses,FastAPI); (uses,MySQL) | √ | LLM | - | - |
| M10 | 我叫王芳，我投了腾讯 | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | (name,王芳); (applied_to,腾讯) | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | √ | LLM | - | - |
| M20 | 改投后端岗了 | (target_role,后端岗) | (applied_to,后端岗位) | (target_role,后端岗) | √ | LLM | - | - |

## 汇总

- 混合架构完全一致：**18/20 = 90%**（v3 无兜底 19/20，残差=LLM 空抽）
- 路径构成：LLM 自身命中 20/20，规则兜底救回 0/20，双空（疑问句）0/20
- LLM 非空且未归一原始输出即完全一致：0/20（原始对照口径，改进仍归因归一化层）

## 差异分析

<!-- ANALYSIS_PLACEHOLDER -->
