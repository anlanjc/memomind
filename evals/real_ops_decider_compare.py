"""LLMOpsDecider 真模型决策对比：规则决策矩阵 vs LLM 决策器（MM-3 会话）。

口径：**决策层单变量对比**——抽取层冻结为 RuleExtractor（两路喂完全相同的
候选事实与 active 记忆快照），唯一变量是决策器（RuleOpsDecider vs
LLMOpsDecider）。判定基准=规则矩阵的输出（mock 评测 100/100 的同一套
确定性金标），量化 LLM 决策与矩阵的分歧模式。

试验收集：把 eval_set_100.json 的 100 条用例按 mock 管线逐轮复放（规则抽取
→ 决策前快照 existing → 规则决策落库推进状态），每个"有候选事实的决策点"
收集为一个试验 (facts, existing, rule_ops)。分层抽样保证各决策模式
（ADD / 撤销 DELETE+ADD / UPDATE:supersede / UPDATE:strengthen / NOOP…）
都有覆盖，≥30 试样。

- 花费：usage 实记账本 .real_ops_ledger.json，上限 ¥1，超限中止；
  curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com（同 v4）。
- 可观测：LLMOpsDecider.last_call_stats 留痕（fallback 触发 /
  UPDATE 未指目标次数）；规则决策器输出与 mock 评测金标同源。

用法（项目根目录）：
    ../.venv/Scripts/python.exe evals/real_ops_decider_compare.py --dry   # 只看抽样分布，不花钱
    ../.venv/Scripts/python.exe evals/real_ops_decider_compare.py         # 真模型对比
产物：evals/real_ops_decider_report.md + evals/real_ops_decider_rows.json
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parents[1]           # memomind/
ROOT = PROJ.parent                                    # 工作区根
sys.path.insert(0, str(PROJ))

from memomind.extract import RuleExtractor  # noqa: E402
from memomind.llm import OpenAICompatibleClient  # noqa: E402
from memomind.ops import LLMOpsDecider, RuleOpsDecider  # noqa: E402
from memomind.schema import (  # noqa: E402
    ExtractedFact,
    MemoryOp,
    MemoryRecord,
    OP_ADD,
    OP_DELETE,
    OP_NOOP,
    OP_UPDATE,
)
from memomind.store import MemoryStore  # noqa: E402

PRICE_IN, PRICE_OUT = 4.0, 12.0
CAP_YUAN = 1.0
PER_PATTERN_CAP = 6          # 每个决策模式最多抽 6 个试验
MIN_TRIALS = 30              # 任务下限
EVALS = Path(__file__).resolve().parent
LEDGER = EVALS / ".real_ops_ledger.json"
OUT_MD = EVALS / "real_ops_decider_report.md"
OUT_JSON = EVALS / "real_ops_decider_rows.json"

T0 = datetime(2026, 7, 1, tzinfo=__import__("datetime").timezone.utc).timestamp()
DAY = 86400.0

# -- 试验收集：复放 eval_set_100，收集决策点 ----------------------------------

def collect_trials() -> list[dict]:
    from memomind.decay import DecayConfig, compact, run_decay

    cases = json.loads((EVALS / "eval_set_100.json").read_text(encoding="utf-8"))
    extractor = RuleExtractor()
    decider = RuleOpsDecider()
    trials: list[dict] = []
    for case in cases:
        store = MemoryStore(":memory:")
        now = T0
        for step_idx, step in enumerate(case["steps"]):
            now += step.get("advance_days", 0.0) * DAY
            for sd in step.get("seeds", []):
                subject, predicate, obj, category, conf, valid_to_days = sd
                fact = ExtractedFact(subject, predicate, obj, category, conf)
                store.add(fact, source_session="seed", now=now,
                          valid_to=(now + valid_to_days * DAY) if valid_to_days is not None else None)
            if step.get("run_decay"):
                run_decay(store, now, DecayConfig())
            if step.get("run_compact"):
                compact(store, now, DecayConfig())
            text = step.get("text") or ""
            if not text:
                continue
            facts = extractor.extract(text, step["session"], now)
            if facts:
                existing = store.list_active(now)
                # deepcopy：决策器 strengthen 的 _advance_state 会改写 state 里的
                # 记录对象，不隔离会污染快照（规则与 LLM 必须看到相同状态才公平）
                rule_ops = decider.decide(copy.deepcopy(facts),
                                          copy.deepcopy(existing), now)
                trials.append(dict(
                    sid=case["sid"], layer=case["layer"], title=case["title"],
                    step_idx=step_idx, text=text, facts=facts, existing=existing,
                    rule_ops=rule_ops,
                ))
            # 与 mock 管线同构：规则决策落库推进状态
            if facts:
                store.apply_ops(decider.decide(copy.deepcopy(facts),
                                               store.list_active(now), now),
                                source_session=step["session"], now=now)
        store.close()
    trials.extend(_synthetic_trials())
    return trials


# -- 模式分类与分层抽样 --------------------------------------------------------

def pattern_of(trial: dict) -> str:
    """决策模式标签：分层抽样的分组键。"""
    ops = trial["rule_ops"]
    if any(f.polarity == "negative" or f.predicate == "withdrawn" for f in trial["facts"]):
        has_target = any(op.op == OP_DELETE for op in ops)
        return "撤销(有旧记忆)" if has_target else "撤销(无旧记忆留档)"
    kinds = []
    for op in ops:
        if op.op == OP_UPDATE:
            kinds.append(f"UPDATE:{op.update_kind}")
        elif op.op == OP_NOOP:
            kinds.append("NOOP:低置信" if "低置信" in op.reason else "NOOP:重复")
        else:
            kinds.append(op.op)
    return "+".join(sorted(set(kinds))) + (f"x{len(ops)}" if len(ops) > len(set(kinds)) else "")


def sample_trials(trials: list[dict]) -> list[dict]:
    by_pattern: dict[str, list[dict]] = {}
    for t in trials:
        by_pattern.setdefault(pattern_of(t), []).append(t)
    picked: list[dict] = []
    # 多操作模式优先（信息量大），单 ADD 模式垫底
    for pat in sorted(by_pattern, key=lambda p: (-p.count("+"), p)):
        group = sorted(by_pattern[pat], key=lambda t: (t["sid"], t["step_idx"]))
        picked.extend(group[:PER_PATTERN_CAP])
    return picked


# -- 语义探针：构造决策矩阵各分支的最小试验 -----------------------------------

def _synthetic_trials() -> list[dict]:
    """eval 集复放覆盖不足的矩阵分支（B1 强化 / B2 重复 / A0 低置信 /
    多目标撤销 / 混合批）用最小合成试验直接探测——决策矩阵的语义微基准。"""
    def rec(pred, obj, conf=0.9, rec_id="r1"):
        return MemoryRecord(id=rec_id, subject="user", predicate=pred, object=obj,
                            category="application", confidence=conf, valid_from=T0,
                            status="active", source_session="s0",
                            created_at=T0, last_accessed=T0)

    def fact(pred, obj, conf=0.9, polarity="positive"):
        return ExtractedFact("user", pred, obj, "application", conf, polarity=polarity)

    R = RuleOpsDecider()
    out: list[dict] = []

    def add(sid, title, facts, existing):
        ops = R.decide(copy.deepcopy(facts), copy.deepcopy(existing))
        out.append(dict(sid=sid, layer="合成-语义探针", title=title, step_idx=0,
                        text=f"（合成）{title}", facts=facts, existing=existing,
                        rule_ops=ops))

    add("S-B1", "重复提及且置信更高：已投美团(0.9)，再投美团(0.95)",
        [fact("applied_to", "美团", 0.95)], [rec("applied_to", "美团", 0.9)])
    add("S-B2", "完全重复同置信：已投美团(0.9)，再投美团(0.9)",
        [fact("applied_to", "美团", 0.9)], [rec("applied_to", "美团", 0.9)])
    add("S-B1S", "技能重复强化：已会Python(0.8)，再说熟悉Python(0.85)",
        [fact("uses", "Python", 0.85)], [rec("uses", "Python", 0.8)])
    add("S-D1E", "状态推进：字节已投(submitted)，再说字节面试中",
        [fact("application_status", "字节跳动:interviewing", 0.95)],
        [rec("application_status", "字节跳动:submitted", 0.9)])
    add("S-C1M", "撤销命中两条：已投美团+已提交，再说取消美团申请",
        [fact("withdrawn", "美团", 0.95, "negative")],
        [rec("applied_to", "美团", 0.9, "r1"),
         rec("application_status", "美团:submitted", 0.9, "r2")])
    add("S-A0", "低置信丢弃：一条0.2置信的偏好",
        [fact("prefers", "远程办公", 0.2)], [])
    add("S-MIX", "混合批：新投快手+同时取消腾讯（腾讯在库）",
        [fact("applied_to", "快手", 0.9), fact("withdrawn", "腾讯", 0.95, "negative")],
        [rec("applied_to", "腾讯", 0.9, "r1"),
         rec("application_status", "腾讯:submitted", 0.9, "r2")])
    add("S-D1N", "身份矛盾：已记姓名李雷，再说叫王芳",
        [ExtractedFact("user", "name", "王芳", "identity", 0.99)],
        [MemoryRecord(id="r1", subject="user", predicate="name", object="李雷",
                      category="identity", confidence=0.99, valid_from=T0,
                      status="active", source_session="s0", created_at=T0,
                      last_accessed=T0)])
    add("S-E1P", "无冲突新偏好：已记目标后端岗，再说想去杭州",
        [ExtractedFact("user", "prefers_city", "杭州", "preference", 0.8)],
        [MemoryRecord(id="r1", subject="user", predicate="target_role", object="后端岗",
                      category="preference", confidence=0.9, valid_from=T0,
                      status="active", source_session="s0", created_at=T0,
                      last_accessed=T0)])
    return out


# -- 动作签名与分歧分类 --------------------------------------------------------

def op_sig(op: MemoryOp, existing: list[MemoryRecord]) -> tuple:
    by_id = {r.id: r for r in existing}
    if op.op == OP_ADD:
        return ("ADD", op.fact.triple_key if op.fact else "?")
    if op.op == OP_UPDATE:
        target = by_id.get(op.target_id)
        tt = target.triple if target else ("?", op.target_id or "?")
        if op.update_kind == "strengthen":
            return ("UPDATE", "strengthen", tt)
        return ("UPDATE", "supersede", tt, op.fact.triple_key if op.fact else "?")
    if op.op == OP_DELETE:
        target = by_id.get(op.target_id)
        tt = target.triple if target else ("?", op.target_id or "?")
        return ("DELETE", tt)
    return ("NOOP",)


def kind_sig(sig: tuple) -> str:
    return sig[0] if sig[0] != "UPDATE" else f"UPDATE:{sig[1]}"


def classify_divergence(rule_sigs: list[tuple], llm_sigs: list[tuple]) -> list[str]:
    kr, kl = Counter(kind_sig(s) for s in rule_sigs), Counter(kind_sig(s) for s in llm_sigs)
    if kr == kl:
        return ["目标/事实错位（动作类型一致）"]
    tags = []
    for kind in sorted(set(kr) | set(kl)):
        a, b = kr.get(kind, 0), kl.get(kind, 0)
        if a > b:
            tags.append(f"规则有LLM缺:{kind}×{a - b}")
        elif b > a:
            tags.append(f"LLM多出:{kind}×{b - a}")
    return tags


# -- LLM 侧 fallback 触发捕获 --------------------------------------------------

class _FallbackCapture(logging.Handler):
    """捕获 memomind.ops 的 ERROR 日志（LLM 决策失败回退的留痕）。"""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.fired = False

    def emit(self, record: logging.LogRecord) -> None:
        self.fired = True


# -- 主流程 --------------------------------------------------------------------

def main() -> int:
    global PER_PATTERN_CAP
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只收集与抽样，不调 LLM")
    ap.add_argument("--per-pattern", type=int, default=PER_PATTERN_CAP)
    args = ap.parse_args()
    PER_PATTERN_CAP = args.per_pattern

    trials = collect_trials()
    print(f"共收集决策点试验 {len(trials)} 个")
    picked = sample_trials(trials)
    dist = Counter(pattern_of(t) for t in picked)
    print(f"抽样 {len(picked)} 个，模式分布：")
    for pat, n in dist.most_common():
        print(f"  {n:3d}  {pat}")
    if args.dry:
        return 0
    if len(picked) < MIN_TRIALS:
        print(f"试样 {len(picked)} < {MIN_TRIALS}，先调大 --per-pattern")
        return 1

    # LLM 客户端（真模型，同 v4 传输层与 key 来源）
    from evals.real_extract_compare_v4 import CurlTransport, load_llm_kwargs

    kw = load_llm_kwargs()
    transport = CurlTransport()
    client = OpenAICompatibleClient(transport=transport, **kw)
    llm_decider = LLMOpsDecider(client)
    rule_decider = RuleOpsDecider()
    capture = _FallbackCapture()
    logging.getLogger("memomind.ops").addHandler(capture)
    logging.getLogger("memomind.ops").setLevel(logging.ERROR)

    ledger_path = LEDGER
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        ledger = {"tokens_in": 0, "tokens_out": 0, "est_cost_yuan": 0.0, "calls": 0,
                  "price_assumption": f"¥{PRICE_IN}/M in, ¥{PRICE_OUT}/M out（保守上限）"}

    def save_ledger() -> None:
        ledger["updated_at"] = datetime.now().isoformat(timespec="seconds")
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = []
    for t in picked:
        rule_sigs = [op_sig(op, t["existing"]) for op in t["rule_ops"]]
        capture.fired = False
        llm_ops = llm_decider.decide(copy.deepcopy(t["facts"]),
                                     copy.deepcopy(t["existing"]), T0)
        stats = dict(llm_decider.last_call_stats)
        llm_sigs = [op_sig(op, t["existing"]) for op in llm_ops]
        exact = rule_sigs == llm_sigs
        ms_match = Counter(rule_sigs) == Counter(llm_sigs)
        div = [] if exact else classify_divergence(rule_sigs, llm_sigs)
        rows.append(dict(
            sid=t["sid"], layer=t["layer"], title=t["title"], step_idx=t["step_idx"],
            text=t["text"],
            facts=[dict(predicate=f.predicate, object=f.object,
                        confidence=f.confidence, polarity=f.polarity) for f in t["facts"]],
            existing=[dict(id=r.id, predicate=r.predicate, object=r.object,
                           confidence=r.confidence) for r in t["existing"]],
            rule_ops=[list(s) for s in rule_sigs],
            llm_ops=[list(s) for s in llm_sigs],
            llm_stats=stats, fallback_fired=capture.fired,
            exact_match=exact, multiset_match=ms_match,
            divergence=div,
            llm_reasons=[op.reason for op in llm_ops],
        ))
        mark = "一致" if exact else ("多重集一致" if ms_match else "分歧:" + ";".join(div))
        fb = " [fallback]" if capture.fired else ""
        print(f"  [{t['sid']}#{t['step_idx']}] {t['text'][:22]!r} {mark}{fb}")

        if transport.usage:
            u = transport.usage[-1]
            ledger["tokens_in"] += int(u.get("prompt_tokens", 0))
            ledger["tokens_out"] += int(u.get("completion_tokens", 0))
            ledger["calls"] += 1
            ledger["est_cost_yuan"] = round(
                ledger["tokens_in"] / 1e6 * PRICE_IN + ledger["tokens_out"] / 1e6 * PRICE_OUT, 4)
            save_ledger()
            if ledger["est_cost_yuan"] >= CAP_YUAN:
                print(f"花费护栏触发（¥{ledger['est_cost_yuan']:.2f} ≥ ¥{CAP_YUAN}），停止")
                break

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(rows)
    exact = sum(1 for r in rows if r["exact_match"])
    ms = sum(1 for r in rows if r["multiset_match"])
    fb = sum(1 for r in rows if r["fallback_fired"])
    ut = sum(1 for r in rows
             if r["llm_stats"].get("delegated_retraction") or r["llm_stats"].get("delegated_update"))
    div_counter: Counter = Counter()
    for r in rows:
        for d in r["divergence"]:
            div_counter[d] += 1
    by_layer: dict[str, list[int]] = {}
    for r in rows:
        agg = by_layer.setdefault(r["layer"], [0, 0])
        agg[0] += 1
        agg[1] += 1 if r["exact_match"] else 0

    L = [
        "# LLMOpsDecider 真模型决策对比（规则决策矩阵基准，MM-3）",
        "",
        "- 口径：决策层单变量对比——抽取层冻结为 RuleExtractor，两路喂完全相同的"
        "候选事实与 active 记忆快照（来自 eval_set_100 复放的决策点）；"
        "判定基准=规则决策矩阵输出（mock 评测 100/100 的同一套确定性金标）。",
        f"- 抽样：全量决策点分层抽样 {n} 个试验（每模式 ≤{PER_PATTERN_CAP}），"
        "模式分布见下；LLM=deepseek-v4-flash（与抽取对比同模型同传输层）。",
        f"- 花费（usage 实测）：{ledger['calls']} 次调用，{ledger['tokens_in']} in + "
        f"{ledger['tokens_out']} out tokens ≈ ¥{ledger['est_cost_yuan']:.2f}"
        f"（上限 ¥{CAP_YUAN}），账本 evals/.real_ops_ledger.json。",
        "- 传输层：curl(schannel) + NO_PROXY=dashscope.aliyuncs.com。",
        "",
        "| 用例 | 输入 | 现有记忆 | 规则矩阵动作 | LLM 动作 | 判定 | 分歧 | LLM 理由 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ex = "无" if not r["existing"] else "; ".join(
            f"({e['predicate']},{e['object']})" for e in r["existing"])
        ro = "; ".join(",".join(map(str, s)) for s in r["rule_ops"]) or "无"
        lo = "; ".join(",".join(map(str, s)) for s in r["llm_ops"]) or "无"
        dv = "; ".join(r["divergence"]) or "-"
        rs = "; ".join(r["llm_reasons"]) or "-"
        verdict = "√" if r["exact_match"] else ("≈" if r["multiset_match"] else "×")
        L.append(f"| {r['sid']}#{r['step_idx']} | {r['text']} | {ex} | {ro} | {lo} | "
                 f"{verdict} | {dv} | {rs} |")
    L += [
        "",
        "## 汇总",
        "",
        f"- 动作序列完全一致：**{exact}/{n} = {exact / n:.0%}**；多重集一致（含顺序差）：{ms}/{n}",
        f"- LLM 异常回退（fallback_error）：{fb}/{n}；结构性分支委托规则版"
        f"（撤销/重复提及 UPDATE 定位）按试样统计见 llm_stats 字段",
        "- 分层一致率见下表（合成-语义探针层 = 矩阵分支的最小合成试验）。",
        "",
        "| 层 | 一致/试验 |",
        "|---|---|",
    ]
    for layer, (tot, ok) in sorted(by_layer.items()):
        L.append(f"| {layer} | {ok}/{tot} |")
    L += [
        "",
        "## 分歧模式分布",
        "",
        "```",
    ]
    for tag, cnt in div_counter.most_common():
        L.append(f"{cnt:3d}  {tag}")
    L += ["```", "", "## 分析", "", "<!-- ANALYSIS_PLACEHOLDER -->", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n明细已写入 {OUT_MD} 与 {OUT_JSON}")
    print(f"汇总：完全一致 {exact}/{n} = {exact / n:.0%}（多重集 {ms}/{n}）；"
          f"fallback {fb}；含结构委托试样 {ut}")
    print(f"花费：¥{ledger['est_cost_yuan']:.2f} / ¥{CAP_YUAN}（{ledger['calls']} 次调用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
