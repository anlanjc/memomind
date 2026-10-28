# memomind 评测集扩容报告 v2（20 → 100 条跨会话用例）

- 产物：`evals/eval_set_100.json`（100 条）/ `evals/build_eval_set100.py`（生成器，可复现）
  / `evals/run_eval_set100.py`（runner）
- 口径：与 v1 完全同构的确定性 mock 管线（RuleExtractor + RuleOpsDecider +
  MockResponder，固定时钟 T0=2026-07-01，无网络）；断言对象是系统状态与检索行为
- **mock 全量：100/100 = 100%**（五层各 20/20），原始输出见
  `evidence/eval_set100_mock_output.txt`
- 期望（金标）不是拍脑袋：全部对着规则表正则、决策矩阵、DecayConfig
  （half_life=30d，min_eff=0.15）的公式推得，跑挂的每一条都先分清
  "金标错 / 用例意图错 / 系统缺陷"三种情况

## 与 v1（scenarios.py 20 条）的差异

| 维度 | v1 | v2 |
|---|---|---|
| 规模 | 20 条（5 维度×4） | 100 条（5 层×20） |
| 分层 | 按系统模块（记忆保持/偏好更新/冲突消解/时效遗忘/冷启动） | 按记忆失效模式（事实更新/冲突撤回/别名归一/时序衰减/多跳召回）——v1 的"维度"是模块视角，v2 是对抗视角：每层专打一类最容易做错的语义 |
| 载体 | Python 场景脚本（check 函数） | JSON 数据文件（声明式期望 schema：active/superseded/archived/gone/count/recall_top/recall_contains/ops/conf 等 12 类断言原语）——用例可被非 Python 工具复用，真模型对比只换 provider 不改用例 |
| 新覆盖 | — | 状态机多跳（submitted→ended→interviewing 复活链）、撤销后重投、重复撤销、差分衰减（置信度 0.85 vs 0.99 在 78 天分界）、访问刷新抗遗忘的对照设计、图邻域/意图映射召回、撤回与替代后的检索不可见性 |
| 冷启动 | 4 条 | 并入事实更新层（U16 一句双事实等已覆盖空库首轮 ADD） |

## 扩容过程抓出的三个真问题（扩容的价值所在）

1. **P1 缺陷：多词 LIKE 检索的 status 过滤失效**（M11 抓出，已修复+回归测试）：
   `search_text` 的 LIKE 兜底 SQL 把多个词组的 OR 与 `AND status=?` 直连——
   AND 优先级高于 OR，status 只约束最后一个词组，其余词组命中的
   superseded/archived 记录全部泄漏进召回（"撤回后检索不再出现"的承诺被打破）。
   修复：OR 组加括号（store.py 一行）+ `test_search_text_status_filters_all_or_groups`
   回归。修复后 memomind 全量 **89 测试绿**。
2. **决策矩阵边界：撤销事实不做 B2 去重**（W11 抓出，未改行为，记录为已知边界）：
   重复"不想投京东了"每次都会 ADD 一条 withdrawn 留档（C1 撤销路径不查重）。
   语义上无害（留档幂等性弱），评测金标按实测语义锁定并加注。
3. **抽取器限制：顿号列表截断**（W15/M06 抓出，用例绕行）："投了腾讯、阿里和字节"
   只抽出腾讯——公司字符类不含`、`，贪婪匹配提前截断。规则表已知边界，
   用例改用"和"连接，报告中留档。

## 真模型抽取对比（抽样 20 条，deepseek-v4-flash）

- 明细：`evals/real_extract_compare.md` + `real_extract_compare_rows.json`
- 完全一致 0/20——差异是系统性的四类：谓词命名体系不一致（16/20，接真模型必须
  先做谓词映射层）、隐含状态不冗余存储（9/20，LLM 不产 application_status:submitted，
  状态机查询失效）、否定极性保留但谓词错挂（W03/W04，比 v1 结论略轻：polarity
  仍能触发撤销路径）、实体归一化分叉（滴滴→滴滴出行，图分裂风险）+ 2 处真实误抽
  （"改投后端岗"被抽成 applied_to 后端岗）
- v1 混合架构结论复验成立且证据更强：规则版的 schema 兼容性是 LLM 抽取不可替代的地基

## 复现

```bash
cd memomind
../.venv/Scripts/python.exe evals/build_eval_set100.py     # 重新生成 JSON
../.venv/Scripts/python.exe evals/run_eval_set100.py       # mock 全量（应 100/100）
../.venv/Scripts/python.exe evals/real_extract_compare.py  # 真模型 20 条对比（需 key）
```

## 已知边界

- LongMemEval 未接入：网络下载不可达（与 pip 同环境），评测集为自建并在本报告留档原因；
  用例 schema 为声明式 JSON，后续接入外部数据集时只需写适配器。
- mock 100% 是"金标与实现自洽"的证据，不是泛化能力证明——真模型对比才是
  语义覆盖的真实考验（见上）。
- 衰减类用例的时间参数按 DecayConfig 默认值精确推得；改配置需同步重推金标
  （生成器里的注释给出了每个天数的推导依据）。
