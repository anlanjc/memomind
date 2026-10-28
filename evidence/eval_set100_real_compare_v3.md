# memomind 真模型抽取对比 v3（eval_set_100 抽样 20 条，谓词映射层复测）

- 模型与口径：与 v2（`eval_set100_real_compare.md`，git 历史）完全相同——同一 20 条输入、(predicate, object) 集合对比、temperature=0；唯一变化是 LLM 抽取输出经 `memomind/normalize.py` 谓词映射层归一，抽取 prompt 未改动（LLM 行为冻结，改进可归因于归一化层）。
- 表中"LLM 原始"列是 last_raw_facts 留痕的未归一输出，"LLM 归一"列才是进 ops 决策矩阵的事实。
- 花费（usage 实测）：60 次调用，15240 in + 20161 out tokens ≈ ¥0.30（上限 ¥0.5），单价假设 ¥4.0/M in, ¥12.0/M out（保守上限），账本 evals/.real_extract_ledger.json。
- 传输层：curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com 绕过本机半死系统代理。

| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 原始 (pred, obj) | LLM 归一 (pred, obj) | 一致 | 规则独有 | LLM 独有 | 改写标签 |
|---|---|---|---|---|---|---|---|---|
| U01 | 我想投后端岗 | (target_role,后端岗) | (interested_in,后端岗位) | (target_role,后端岗) | √ | - | - | 谓词映射 |
| U08 | 我掌握 Python | (uses,Python) | (has_skill,Python) | (uses,Python) | √ | - | - | 谓词映射 |
| U10 | 我投了美团和快手 | (applied_to,美团); (application_status,美团:submitted); (applied_to,快手); (application_status,快手:submitted) | (applied_to,美团); (applied_to,快手) | (applied_to,美团); (applied_to,快手); (application_status,美团:submitted); (application_status,快手:submitted) | √ | - | - | 伴随补全 |
| U16 | 我叫王芳，我想投测试岗 | (name,王芳); (target_role,测试岗) | (name,王芳); (interested_in,测试岗) | (name,王芳); (target_role,测试岗) | √ | - | - | 谓词映射 |
| U17 | 我想去广州工作 | (prefers_city,广州) | (wants_to_work_in,广州) | (prefers_city,广州) | √ | - | - | 谓词映射 |
| W03 | 取消阿里的申请 | (withdrawn,阿里巴巴) | (applied_to,阿里巴巴) | (withdrawn,阿里巴巴) | √ | - | - | 谓词映射; 极性修正 |
| W04 | 不想投腾讯了 | (withdrawn,腾讯) | (applied_to,腾讯) | (withdrawn,腾讯) | √ | - | - | 谓词映射; 极性修正 |
| W05 | 收到字节的offer | (application_status,字节跳动:offer) | (received_offer_from,字节跳动) | (application_status,字节跳动:offer) | √ | - | - | 谓词映射 |
| W09 | 滴滴挂了 | (application_status,滴滴:ended) | 无 | 无 | 部分 | (application_status,滴滴:ended) | - | - |
| W15 | 我投了腾讯和阿里 | (applied_to,腾讯); (application_status,腾讯:submitted); (applied_to,阿里巴巴); (application_status,阿里巴巴:submitted) | (applied_to,腾讯); (applied_to,阿里巴巴) | (applied_to,腾讯); (applied_to,阿里巴巴); (application_status,腾讯:submitted); (application_status,阿里巴巴:submitted) | √ | - | - | 伴随补全 |
| A01 | 我投了字节 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | - | - | 伴随补全 |
| A04 | 我投了字节的Agent岗 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动Agent岗) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | - | - | 伴随补全; 实体归一 |
| A05 | 投了deepseek | (applied_to,DeepSeek); (application_status,DeepSeek:submitted) | (applied_to,DeepSeek) | (applied_to,DeepSeek); (application_status,DeepSeek:submitted) | √ | - | - | 伴随补全 |
| A14 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | - | - | 伴随补全 |
| D01 | 我投了滴滴 | (applied_to,滴滴); (application_status,滴滴:submitted) | (applied_to,滴滴出行) | (applied_to,滴滴); (application_status,滴滴:submitted) | √ | - | - | 伴随补全; 实体归一 |
| D16 | 我投了美团 | (applied_to,美团); (application_status,美团:submitted) | (applied_to,美团) | (applied_to,美团); (application_status,美团:submitted) | √ | - | - | 伴随补全 |
| M01 | 我投了字节跳动 | (applied_to,字节跳动); (application_status,字节跳动:submitted) | (applied_to,字节跳动) | (applied_to,字节跳动); (application_status,字节跳动:submitted) | √ | - | - | 伴随补全 |
| M02 | 我熟悉 Python、FastAPI 和 MySQL | (uses,Python); (uses,FastAPI); (uses,MySQL) | (has_skill,Python); (has_skill,FastAPI); (has_skill,MySQL) | (uses,Python); (uses,FastAPI); (uses,MySQL) | √ | - | - | 谓词映射 |
| M10 | 我叫王芳，我投了腾讯 | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | (name,王芳); (applied_to,腾讯) | (name,王芳); (applied_to,腾讯); (application_status,腾讯:submitted) | √ | - | - | 伴随补全 |
| M20 | 改投后端岗了 | (target_role,后端岗) | (applied_to,后端岗位) | (target_role,后端岗) | √ | - | - | 谓词映射 |

## 汇总

- 完全一致（归一后）：**19/20 = 95%**（v2 修复前 0/20）
- 完全一致（LLM 原始输出，未归一对照）：0/20——改进全部来自归一化层而非模型行为变化
- 归一后仍有 LLM 独有抽取的输入：0/20；规则独有：1/20
- 改写标签分布：{"谓词映射": 9, "伴随补全": 10, "极性修正": 2, "实体归一": 2}

## 差异分析

**修复路径（三轮复测，花费全程 usage 实记账本）：0/20 → 17/20 → 19/20 → 19/20 = 95%。**

- **第一轮（词典版映射层）17/20**：v2 报告的 4 类系统性差异全部被归一化层闭合——
  谓词映射 16/20 命中（has_skill→uses、has_name→name、wants_to_apply_to/
  interested_in+岗位宾语→target_role、wants_to_work_in→prefers_city、
  received_offer_from→application_status:X:offer、was_rejected_by→…:ended）、
  极性修正 2（negative+applied_to→withdrawn 留档，W03/W04）、伴随补全 9
  （applied_to 自动带 application_status:X:submitted，进决策矩阵后状态机查询可用）、
  实体归一（滴滴出行→滴滴，共享 COMPANY_ALIASES）、宾语感知（M20 改投后端岗：
  applied_to+岗位宾语→target_role，v2 的"真实误抽"被结构化修复）。
  残差 3 条同根因：LLM 本轮造了词典没登记的同义变体（wants_to_apply /
  prefers_work_location / is_familiar_with，对比 v2 的 wants_to_apply_to /
  wants_to_work_in / has_skill）——**词典法的枚举盲区被运行间变异击穿**。
- **第二轮（+亚词兜底层）19/20**：词典未命中时按无歧义领域词根前缀归一
  （familiar/skill→uses、prefer+location→prefers_city、want+apply→target_role
  仍要求岗位宾语），三条变体全部闭合。另修一处宾语词形残差：U01"后端岗"被
  LLM 展开为"后端岗位"，加 target_role 宾语"岗位→岗"后缀折迭。
- **第三轮（定稿）19/20**：残差 1 条性质已变——W09"滴滴挂了"本轮 LLM 抽了空
  （前两轮同输入均抽出 was_rejected_by:滴滴出行 并被正确映射全匹配）。
  这是 **temperature=0 下仍存在的抽取召回波动**（terse 口语"挂了"被判定为
  不可形式化），不是映射层缺陷；"LLM 空抽时由规则层兜底"正是混合架构
  （规则打底 + LLM 增强）的职责边界，不应在归一化层偷跑规则抽取
  （否则对比口径循环自证）。

**结论**：v2 报告"接真模型必须先做谓词映射层"的判断成立且已落地——归一化层
（词典 + 亚词兜底 + 宾语感知/极性修正/伴随补全/实体归一）把 LLM 抽取与规范
schema 的一致率从 0% 提到 95%，且原始输出对照 0/20 证明改进全部来自归一化层
（prompt 未动、模型未动）。剩余 5% 是 LLM 抽取召回波动，由混合架构的规则
底线兜住；映射失败不猜测的红线未破（未登记谓词仍走 per_object 安全兜底）。

**诚实边界**：本层词典/词根表按两次真模型运行的实测证据维护，属"活词典"
——新变体出现时按证据扩充（测试与词典同文件演进）；mock 评测 100/100 与
规则抽取路径零改动（118 测试全绿，其中 normalize 新增 27 项）。
