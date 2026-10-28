# TAKEOVER —— memomind 接手指南

> 给下一个人（或三个月后的自己）：这个文档回答"从哪下手、改哪里、做什么实验"。
> 先跑通三件事再动代码：`pytest -q`（70 绿）、`python -m evals.run_evals`（20/20）、
> `python scripts/demo.py`（看记忆轨迹）。这三件事是本项目的回归防线，**任何改动之后
> 必须仍然全绿，改坏了要么修代码要么改场景并说明理由**。

## 0. 十分钟读懂代码

按数据流读，每个文件头部有设计文档：

```
schema.py（数据长什么样）→ store.py（存哪、怎么查）
→ extract.py（事实从哪来）→ ops.py（能不能写进去）★
→ retrieve.py（怎么取出来）→ decay.py（怎么没的）
→ chat.py（串起来）→ api.py（暴露出去）
```

核心心智模型只有一句话：**记忆 = 带时间有效性与置信度的三元组断言；写入必须过
决策矩阵；读取按"相关度×置信度×时间衰减"排序；遗忘分逻辑删除与物理删除两层。**

## 1. 白板重写清单（面试前必须能脱稿重写的三块）

### 1.1 ops 决策器（`memomind/ops.py::RuleOpsDecider`）

- 要能默写决策矩阵七行：A0 低置信 NOOP / C1 撤销 DELETE+ADD / B1 重复强化 /
  B2 完全重复 NOOP / D1 矛盾 supersede / D2 多值并存 / E1 新增 ADD；
- 要能默写冲突键三档：functional=(s,p)、entity=(s,p,实体)、per_object=(s,p,o)，
  以及为什么未知谓词默认 per_object（宁可并存不可误杀）；
- 要能解释 `_decide_one_inner` + `_advance_state` 的"模拟状态"为什么必须存在
  （同一轮内先投后撤的自洽性，不依赖数据库即时落库）；
- 白板练习：新增谓词 `internship_at`（单值）和 `skill_plan`（多值）需要改哪里？
  （答案：`PredicatePolicy.functional` / `per_object`，其他代码零改动——这就是
  策略与机制分离的价值。）

### 1.2 retrieve 排序（`memomind/retrieve.py`）

- 排序公式：`base(词面×2 + 意图×4 + 图×3) × confidence × 0.5^(闲置天数/30)`；
- 三路召回各自解决什么问题：FTS5 管词面、意图映射管"问题与记忆零词面交集"（这是
  无 embedding 时对语义检索的最低成本近似）、图邻域管"实体关联记忆"；
- 两处易错点：召回必须 `touch`（遗忘时钟的输入）；注入块必须按 `max_chars` 预算
  截断（LLM 上下文成本上限）；
- 白板练习：把意图映射换成 embedding 召回，哪些代码不动？（`retrieve()` 的 3) 号
  路换实现；评分/截断/渲染全不动。）

### 1.3 decay（`memomind/decay.py`）

- 三种遗忘的语义区分：过期归档（valid_to）≠ 衰减归档（闲置×置信度低于阈值）≠
  compaction（物理 GC，只清 superseded/archived 超保留期的）；
- 半衰期模型 `conf × 0.5^(idle/HL)`：为什么用半衰期而不是线性衰减（无界、不可解释）；
- 与 retrieve 的耦合：`touch` 刷新 last_accessed 是"常用记忆抗遗忘"的机制，
  删掉 touch 评测 E15 会挂。

## 2. 必做实验 5 个（每个都有假设-操作-观察）

1. **半衰期标定**：把 `DecayConfig.half_life_days` 从 30 改成 7/14/60/180，重跑
   `python -m evals.run_evals`。观察：E13（120 天归档）在 60/180 时会失败——
   体会"遗忘参数是产品决策，不是数学题"。记录每个参数下 20 场景的通过数。
2. **冲突键误杀实验**：把 `applied_to` 从 per_object 改成 functional（改一行
   `PredicatePolicy`），重跑评测。观察：E02/E18 等多公司场景开始失败——理解
   "冲突范围声明错了，正确性全线崩"。改回来。
3. **去掉决策层直写**：在 `chat.py` 里跳过 `ops_decider.decide` 直接 `store.add`，
   跑 E05/E07/E20。观察：同一偏好存成两条、重复陈述翻倍、NOOP 消失——用数据证明
   "决策层是记忆质量的根"。（这是面试时"为什么不让 LLM 直接写库"的实证答案。）
4. **检索权重敏感性**：把 `w_intent` 从 4.0 降到 1.0，跑 E01/E03/E04/E19。
   观察：意图召回仍在（via=intent），但排序被词面/图命中挤掉，top1 可能换人——
   体会多路召回的权重就是产品排序策略。
5. **接真模型对比**：设好 `MEMOMIND_LLM_API_KEY`（DashScope 兼容），把
   `evals/run_evals.py::build_pipeline` 换成 OpenAICompatibleExtractor +
   LLMOpsDecider，跑同一套 20 场景。记录真实模型的分维度正确率与失败案例
   （通常是抽取谓词不稳定），把对比表写进 README——这是从"mock 正确"到
   "真模型可用"的差距量化。

## 3. 原创扩展 3 个（按投入产出比排序）

1. **接入 miniagent 做带记忆的 agent**：把 `MemoChat` 的"注入块"喂给一个 tool-using
   agent（同工作区 miniagent / askbi 的执行循环），记忆作为 system 上下文 +
   `remember/search_memory` 两个工具暴露。验收：agent 能在多轮任务里复用第一次
   会话里说过的偏好。工作量约 1-2 天，简历叙事从"记忆库"升级为"带记忆的 agent"。
2. **图查询 DSL**：在 `store.py` 上加一个小查询语言，例如
   `status:submitted company:字节 since:2026-08 -> timeline`，编译成
   networkx/SQL 查询，暴露 `GET /query?q=...`。把"记忆浏览器"升级成"记忆分析器"。
   工作量 2-3 天。
3. **记忆导入导出**：`POST /export`（全库 JSONL，含 superseded 审计）+
   `POST /import`（幂等：走完整 ops 决策管线，所以导入天然去重/消解）。这让记忆
   可迁移、可备份，也顺带验证"决策层是唯一写入口"的设计。工作量 1 天。

## 4. 工程注意事项

- **Windows + Git Bash**：pip 一律加 `-i https://pypi.org/simple/`（镜像 403）；
- 时钟全部可注入（`FakeClock` in `tests/conftest.py`），新代码**不要直接调
  `time.time()`**（decay/api 里的 `now` 参数模式照抄）；
- FTS5 是 external-content + 触发器同步，别绕过 `store` 的写方法手工 UPDATE 表
  ——触发器虽然会同步 FTS，但状态语义（supersede 封口 valid_to）会丢；
- SQLite 连接 `check_same_thread=False`（FastAPI 线程池需要），单写者假设，
  别加并发写；
- 每个测试/评测场景断言的是**状态与检索行为**，不是应答文本——换 responder 不应
  打破测试；
- 评测口径：确定性 mock 模式的数字已进 README；换真模型后重跑同命令更新表格，
  并保留两列对比。

## 5. 快速排错

| 症状 | 大概率原因 |
|---|---|
| FTS 召回不到 2 字中文词（"字节"） | trigram tokenizer 下 2 字词无 3-gram，走的是 LIKE 兜底；查 `store.search_text` 是否被绕过 |
| 评测 E15 挂（80 天记忆没活下来） | 检索没 touch（last_accessed 没刷新），查 `Retriever.retrieve` 第 5 步 |
| API 报 `MissingLLMConfigError` | 没设 `MEMOMIND_LLM_API_KEY`；离线用途不需要它，只有 API 层在 key 存在时才走 LLM |
| 冲突没消解（两条 active 同键） | 冲突键档位声明错，查 `PredicatePolicy.scope_of` |
| pytest 收集失败 | 必须在项目根目录跑（pyproject.toml 里 `pythonpath=["."]`） |
