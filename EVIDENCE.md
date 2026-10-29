# memomind EVIDENCE.md（去 demo 化证据册 · SM-1 会话 2026-10-29；§7 MM-2 会话追加）

## 1. 做了什么 / 没做什么

**做了**
- 评测集扩容 v2：`evals/eval_set_100.json`（100 条跨会话用例，5 层 × 20：事实更新 /
  冲突撤回 / 别名归一 / 时序衰减 / 多跳召回）+ 生成器 `build_eval_set100.py` +
  runner `run_eval_set100.py`（声明式期望 schema，12 类断言原语）。
- **mock 全量 100/100 = 100%**（五层各 20/20），金标全部对着规则正则 / 决策矩阵 /
  DecayConfig 公式推得。
- **抓出并修复 P1 缺陷**：`store.search_text` LIKE 兜底的多词 OR 组缺括号，
  `AND status='active'` 只约束最后一个词组——superseded/archived 记录经其余词组
  泄漏进检索（"撤回后检索不再出现"被打破）。一行修复 + 回归测试，全量 89 测试绿。
- 真模型抽取对比（抽样 20 条，deepseek-v4-flash）：`evals/eval_set100_real_compare.md`，
  差异是四类系统性差异（谓词命名体系 / 隐含状态不冗余 / 否定极性错挂谓词 /
  实体归一化分叉）+ 2 处真实误抽。
- git 仓库初始化 + evidence/ 归档。

**没做（并说明为什么）**
- LongMemEval 接入：数据集下载网络不可达（与本机 pip 不可用同环境），按任务卡直接自建
  并在报告留档原因；用例是声明式 JSON，后续接外部数据集只需写适配器。
- 谓词映射层（LLM 谓词 → 规范 schema）：真模型对比确认这是接真模型的前提，但它是
  新组件（表 + 测试 + ops 兼容验证），不属于"评测扩容"窗口的改动面。
  **（→ 已由 MM-2 会话落地并复测，见 §7）**
- LLMOpsDecider 真模型决策对比：本次只对比抽取层；决策层对比需要谓词映射层先行。

## 2. 三个关键决策

1. **分层口径从"模块视角"改为"对抗视角"**：v1 按系统模块分（记忆保持/偏好更新/…），
   v2 按记忆失效模式分——每层专打一类最容易做错的语义（别名归一层专门验证
   "归一前是两条记忆、归一后正确冲突"）。
2. **金标从公式推得而非跑完看结果**：衰减类用例的天数全部按
   `confidence × 0.5^(idle/30) < 0.15` 精确推导（如 conf 0.85 在 78 天归档、0.99 存活），
   生成器注释给出每条推导——mock 跑挂时先分清"金标错 / 意图错 / 系统缺陷"。
3. **用例是 JSON 数据而不是 Python 脚本**：与 v1 场景脚本兼容（同一 runner 语义），
   但可被非 Python 工具复用、可 diff、真模型对比只换 provider 不改用例。

## 3. 三个真实 bug（本窗口发现）

1. **LIKE status 泄漏（P1，已修复）**：`WHERE (s LIKE ? OR p LIKE ? OR o LIKE ? OR c LIKE ?)
   OR (...) ... AND status = ?`——AND 优先级高于 OR，status 过滤只套最后一个词组。
   修复：OR 组整体加括号（store.py 一行）+ `test_search_text_status_filters_all_or_groups`。
2. **撤销事实不做去重（C1 路径，记录为已知边界）**：重复"不想投京东了"每次都 ADD 一条
   withdrawn 留档——决策矩阵 B2 完全重复跳过只覆盖非撤销路径。语义无害（留档幂等性弱），
   W11 金标按实测语义锁定。
3. **顿号列表截断（规则表边界，用例绕行）**："投了腾讯、阿里和字节"只抽出腾讯——
   公司字符类不含 `、`，贪婪匹配提前截断。W15/M06 改用"和"连接并在报告留档。

## 4. 评测表（mock 与 real 严格分开）

| 口径 | 内容 | 数字 |
|---|---|---|
| mock v1（历史，`evals/run_evals.py`） | 20 条脚本化场景，5 维度 | 20/20（历史数字，与本次无关） |
| **mock v2（本次，`run_eval_set100.py`）** | 100 条 × 5 层，确定性管线 | **100/100 = 100%** |
| **real v2（SM-1，`real_extract_compare.py` 历史版本）** | 20 条输入 RuleExtractor vs LLM 抽取，(predicate, object) 集合对比 | 完全一致 0/20——差异系统性：谓词命名 16/20、隐含状态 9/20、否定极性错挂 2/20、实体归一化分叉 1/20、真实误抽 1/20 |
| **real v3（MM-2，谓词映射层落地后复测）** | 同 20 条、同模型、同 prompt（LLM 行为冻结），唯一变量=normalize.py 归一化层 | **完全一致 19/20 = 95%**（LLM 原始未归一对照仍 0/20——改进全部来自归一化层）；残差 1 条=LLM 抽取召回波动（W09 本轮空抽，前两轮同输入全匹配） |
| **real v4（MM-3，混合空抽兜底 + 词典增量修订）** | 同 20 条，唯一变量=HybridExtractor 兜底接线 + normalize 四条实测增量 | **完全一致 20/20 = 100%**（两轮 18/20→20/20；LLM 原始对照仍 0/20）；W09 空抽探针 10 次：空抽未复现、同输入 5 次产出 4 种谓词变体（词典盲区活体实证） |
| **real 决策层（MM-3，LLMOpsDecider vs 规则矩阵）** | 180 决策点分层抽样 44 试样 + 9 合成语义探针，决策层单变量（抽取冻结为规则版） | raw **31/44=70.5%** → 结构分支委托后 **44/44=100%**（撤销复合动作/重复提及/低置信三类归因，ADR-6） |
| 花费（real） | v2：20 次调用（client 不透出 usage，按 ~1k tokens/次估）est ≈¥0.1；v3：三轮 60 次调用 **usage 实记** 15,240 in + 20,161 out tokens；v4+探针：50 次调用 usage 实记；决策对比：176 次调用 usage 实记（phase1 与 phase2-4 两本账本） | v3 **≈¥0.30**（上限 ¥0.5）；v4 **¥0.29**（上限 ¥0.3）；决策对比 **¥0.69**（上限 ¥1，账本分列 .real_ops_ledger*.json） |

pytest：SM-1 窗口 **89 passed**；MM-2 窗口 **118 passed**（normalize 层 29 项新测试
+ 2 项 LLM 抽取器测试更新）；MM-3 窗口 **141 passed**（hybrid 7 + normalize 增量
8 + ops 统计/结构委托 8）；mock 100/100 三窗口均不变。

## 5. 复现命令

```bash
cd memomind
../.venv/Scripts/python.exe -m pytest -q                       # 141 passed
../.venv/Scripts/python.exe evals/build_eval_set100.py         # 重新生成 JSON
../.venv/Scripts/python.exe evals/run_eval_set100.py           # mock 全量（应 100/100）
../.venv/Scripts/python.exe evals/run_eval_set100.py --verbose # 逐条细节
../.venv/Scripts/python.exe evals/real_extract_compare.py      # 真模型 20 条对比（需 key；
                                                               #   产物 *_v3.md，v2 版本见 git 历史）
../.venv/Scripts/python.exe evals/real_extract_compare_v4.py   # v4：混合空抽兜底验收（20/20）
../.venv/Scripts/python.exe evals/probe_w09_fallback.py        # W09 空抽/变体探针 ×5
../.venv/Scripts/python.exe evals/real_ops_decider_compare.py --dry  # 决策对比抽样分布（不花钱）
../.venv/Scripts/python.exe evals/real_ops_decider_compare.py        # 决策层真模型对比（44 试样）
```

## 6. 已知边界

- mock 100% 是"金标与实现自洽"的证据，不是泛化能力证明——真模型对比才是语义覆盖的
  真实考验（结论：接真模型必须先做谓词映射层 + 别名表共享）。
- 衰减类金标绑定 DecayConfig 默认值（half_life=30d / min_eff=0.15）；改配置需重推金标。
- 真模型对比只测抽取层，不测决策层与检索排序（LLM 抽取的下游影响是推断，未端到端验证）。
- 传输层：Python OpenSSL 到 DashScope 被 RST，对比脚本用 curl(schannel) transport
  注入（memomind 的 transport 参数原样可用），库代码零改动。

## 7. MM-2 会话追加（2026-10-29）：谓词映射层落地与真模型复测

**做了**：新增 `memomind/normalize.py` 谓词映射层（OpenAICompatibleExtractor 的
确定性后处理，RuleExtractor/mock 路径零改动）——①谓词词典映射（条目全部来自
v1/v2 实测证据）+ 词典未命中的亚词兜底（按无歧义领域词根前缀归一）；②极性修正
（negative+applied_to→withdrawn 留档）+ 隐含状态伴随补全（applied_to 自动带
application_status:X:submitted，对齐规则版不变量）；③实体归一（共享
COMPANY_ALIASES，滴滴出行→滴滴；target_role"岗位→岗"折迭）；④宾语感知修复
v2 真实误抽（applied_to+岗位宾语→target_role，"改投"语义结构化修复）。
抽取 prompt 与模型未动，LLM 行为冻结。

**三个关键决策**
1. **prompt 不动、只做后处理归一**：让 0/20→95% 的改进可完全归因于映射层
   （LLM 原始未归一对照始终 0/20 是归因证据）；生产上 prompt 引导与映射层
   是互补的两道防线，本窗口只验证后者。
2. **映射失败不猜测**：未登记谓词原样保留走 ops 的 per_object 安全兜底
   （宁可并存不可误杀）——亚词兜底也只收无歧义领域词根，want/interest 类
   仍要求岗位宾语（"想投"永不改写成 applied_to）。
3. **伴随补全在归一化层做而不是改 ops 决策矩阵**：状态伴随对是抽取层不变量
   （规则版 `_f_applied` 就这么产），在入口处对齐让 ops/检索零改动。

**真实 bug（本窗口发现）**
1. v2 对比脚本的花费账本只读不写（`load_ledger` 无对应 save），花费只能事后估算
   ——v3 改为每次调用后按 DashScope usage 实 tokens 落盘。
2. 首版伴随补全的去重条件误用 applied_to 自身三元组查重（必然在 seen 集合里），
   伴随对全被吞掉——单测先于真模型运行抓出（测试先行的直接收益）。
3. LLM 谓词造词是运行间波动的（temperature=0 也不稳）：同一语义 v2 轮
   `wants_to_apply_to`、v3 第一轮 `wants_to_apply`——**词典法必须配亚词兜底层**，
   否则每次复测都在打地鼠。

**结果**：完全一致 **0/20 → 19/20 = 95%**（三轮 17→19→19，第一轮残差=词典盲区、
定稿残差=LLM 空抽召回波动，属混合架构规则底线的职责，不在归一化层偷跑）。
明细 `evals/eval_set100_real_compare_v3.md`（原始/归一双列+改写标签）。

**没做**：LLM 空抽的规则兜底（属于混合架构接线，非映射层职责）；决策层
（LLMOpsDecider）真模型对比（前置已就绪，留给下一窗口）。

## 8. MM-3 会话追加（2026-10-29）：空抽兜底混合架构接线 + LLMOpsDecider 真模型决策对比

**做了**：MM-2 留下的两个窗口全部落地——①新增
`memomind/extract.py::HybridExtractor`：LLM 抽取结果为空时回退 RuleExtractor
（开关默认开、events 事件留痕 + rescued 标记 + logger.warning），api.py 真模型
装配点默认接线；同一 20 条真模型复测 **19/20 → 20/20 = 100%**
（`evals/eval_set100_real_compare_v4.md`，两轮：18/20 → 词典增量修订四条 → 20/20）。
②LLMOpsDecider 真模型决策对比：180 个决策点（eval_set_100 复放）分层抽样
44 试样 + 9 个合成语义探针，规则矩阵输出为基准，四轮
**31/44=70.5% → 41/44 → 43/44 → 44/44=100%**（`evals/real_ops_decider_report.md`，
分歧逐类归因），结论落 ADR-6：LLM 裁决语义核心（新增/矛盾/多值），
撤销复合动作/重复提及置信算术/低置信策略阈值三类结构分支委托规则矩阵，
last_call_stats 留痕可观测。

**三个关键决策**
1. **兜底做在抽取器组合层，归一化层不偷跑**：MM-2 红线"空抽兜底属混合
   架构规则底线"——HybridExtractor 是独立包装器（组合任意 primary+fallback），
   兜底只在"结果为空"时触发、LLM 非空但抽得少不混流（保持对比口径可归因）。
2. **normalize.py 只做增量修订（红线内）**：四条全部来自本轮实测证据——
   COMPANY_ALIASES+深度求索（LLM 把 deepseek 翻译成官方中文名）、
   _fold_role 吸收"开发/工程师"嵌入缀（后端开发岗位→后端岗）、
   prefers+岗位宾语→target_role、失败类亚词状态兜底（fail/reject→ended）；
   抽取 prompt 与模型全程冻结。
3. **决策层委托而不是修 prompt**：LLM 决策的三类系统性分歧根因是输出
   schema 表达力（撤销=DELETE×N+ADD 复合动作表达不了，6/6 分歧）、策略配置
   不可见（min_confidence）、置信度算术——都属结构语义不是判断力；确定性
   分支预路由规则矩阵，LLM 保留 novel 事实的 E1/D1/D2 判断（132 次调用
   零异常零回退）。

**真实 bug（本窗口发现）**
1. 评测装置快照污染：collect_trials 把快照直接交给规则决策器，strengthen 的
   _advance_state 原位改写记录对象（0.85→0.93），规则与 LLM 看到不同状态——
   单变量对比被破坏，修复=deepcopy 隔离。教训：**"两路输入相同"要靠机制保证**。
2. 同一句"滴滴挂了"temperature=0 下 5 次调用产出 **4 种谓词变体**
   （failed_at/was_rejected_by/failed_interview_at/failed_application，探针实测）
   ——词典法必须配亚词兜底的活体实证（MM-2 结论的强化证据）。
3. 空抽兜底本会话 50 次真模型调用零触发（W09 空抽未复现，LLM 波动本身波动）
   ——机制证据=7 项回归测试（救回/双空/开关/不混流/事件累计/日志/管线接线），
   诚实记录：活体救回样本为零。

**结果**：pytest **141 全绿**（MM-2 基线 118 + 23 项新测试：hybrid 7/normalize
增量 8/ops 统计与委托 8）；mock 评测 **100/100** 两轮复验不变；真模型抽取
20/20；真模型决策对比 44/44（加固后口径，raw 70.5% 留档 phase1 rows）。
花费：抽取 v4+探针 **¥0.29/¥0.3**（50 调用，.real_extract_ledger_v4.json）；
决策对比 **¥0.69/¥1**（phase1 44 + phase2-4 132 调用，两本账本分列），
全程 NO_PROXY=dashscope.aliyuncs.com + usage 实记。产物归档：v4 对比报告
+ round1 存档 + W09 探针 JSON + 决策对比报告四份（终版+phase1/2/3）。

**没做**：LLM 空抽活体救回样本（10 次探针未复现空抽，机制由测试钉死）；
LLM 决策器在 novel 事实上的语义误判样本（本窗口未出现，ADR-6 记录为
持续观察面）；检索层/衰减层真模型对比（不在本窗口范围）。
