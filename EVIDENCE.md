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
| 花费（real） | v2：20 次调用（client 不透出 usage，按 ~1k tokens/次估）est ≈¥0.1；v3：三轮 60 次调用 **usage 实记** 15,240 in + 20,161 out tokens | v3 **≈¥0.30**（上限 ¥0.5 未超，账本 `evals/.real_extract_ledger.json`） |

pytest：SM-1 窗口 **89 passed**；MM-2 窗口 **118 passed**（normalize 层 29 项新测试
+ 2 项 LLM 抽取器测试更新）；mock 100/100 两窗口均不变。

## 5. 复现命令

```bash
cd memomind
../.venv/Scripts/python.exe -m pytest -q                       # 118 passed
../.venv/Scripts/python.exe evals/build_eval_set100.py         # 重新生成 JSON
../.venv/Scripts/python.exe evals/run_eval_set100.py           # mock 全量（应 100/100）
../.venv/Scripts/python.exe evals/run_eval_set100.py --verbose # 逐条细节
../.venv/Scripts/python.exe evals/real_extract_compare.py      # 真模型 20 条对比（需 key；
                                                               #   产物 *_v3.md，v2 版本见 git 历史）
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
