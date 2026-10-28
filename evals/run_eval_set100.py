"""评测执行器 v2：从 evals/eval_set_100.json 加载 100 条分层用例，跑确定性 mock 管线。

与 v1（run_evals.py，20 条脚本化场景）同一套确定性口径：
RuleExtractor + RuleOpsDecider + MockResponder，固定起始时间，无网络。
接真模型时把 build_pipeline 里的 provider 换掉即可，用例与期望不变。

用法（项目根目录，根 .venv）：
    .venv/Scripts/python.exe evals/run_eval_set100.py            # 汇总表
    .venv/Scripts/python.exe evals/run_eval_set100.py --verbose  # 逐条细节
    .venv/Scripts/python.exe evals/run_eval_set100.py --json     # 追加 JSON 明细
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memomind.chat import MemoChat
from memomind.decay import DecayConfig, compact, run_decay
from memomind.extract import RuleExtractor
from memomind.ops import RuleOpsDecider
from memomind.retrieve import RetrievalConfig, Retriever
from memomind.store import MemoryStore

T0 = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc).timestamp()
DAY = 86400.0
EVALS = Path(__file__).resolve().parent


@dataclass
class CaseResult:
    sid: str
    layer: str
    title: str
    passed: bool
    detail: str


def build_pipeline(store: MemoryStore) -> MemoChat:
    """确定性管线（评测口径）。接真模型时只改这里。"""
    return MemoChat(
        store,
        RuleExtractor(),
        ops_decider=RuleOpsDecider(),
        retriever=Retriever(store, RetrievalConfig()),
    )


def run_case(case: dict) -> CaseResult:
    store = MemoryStore(":memory:")
    chat = build_pipeline(store)
    results: list = []
    now = T0
    for step in case["steps"]:
        now += step.get("advance_days", 0.0) * DAY
        for sd in step.get("seeds", []):
            from memomind.schema import ExtractedFact

            subject, predicate, obj, category, conf, valid_to_days = sd
            fact = ExtractedFact(subject, predicate, obj, category, conf)
            store.add(
                fact,
                source_session="seed",
                now=now,
                valid_to=(now + valid_to_days * DAY) if valid_to_days is not None else None,
            )
        if step.get("run_decay"):
            run_decay(store, now, DecayConfig())
        if step.get("run_compact"):
            compact(store, now, DecayConfig())
        if step.get("text"):
            results.append(chat.handle(step["session"], step["text"], now=now))

    ok, detail = check_expect(case["expect"], store, results)
    return CaseResult(case["sid"], case["layer"], case["title"], ok, detail)


def _has(records: list, predicate: str, obj: str) -> bool:
    return any(r.predicate == predicate and r.object == obj for r in records)


def check_expect(exp: dict, store: MemoryStore, results: list) -> tuple[bool, str]:
    fails: list[str] = []
    active = store.list(status="active")
    superseded = store.list(status="superseded")
    archived = store.list(status="archived")
    everything = store.list()

    for p, o in exp.get("active", []):
        if not _has(active, p, o):
            fails.append(f"缺active({p},{o})")
    for p, o in exp.get("superseded", []):
        if not _has(superseded, p, o):
            fails.append(f"缺superseded({p},{o})")
    for p, o in exp.get("archived", []):
        if not _has(archived, p, o):
            fails.append(f"缺archived({p},{o})")
    for p, o in exp.get("absent_active", []):
        if _has(active, p, o):
            fails.append(f"不应active({p},{o})")
    for p, o in exp.get("gone", []):
        if _has(everything, p, o):
            fails.append(f"应物理删除({p},{o})")
    if "count_active" in exp and len(active) != exp["count_active"]:
        fails.append(f"active总数{len(active)}!={exp['count_active']}")
    for p, n in (exp.get("count_active_pred") or {}).items():
        got = sum(1 for r in active if r.predicate == p)
        if got != n:
            fails.append(f"active[{p}]={got}!={n}")
    if "conf_gt" in exp:
        for p, o, v in exp["conf_gt"]:
            rec = next((r for r in active if r.predicate == p and r.object == o), None)
            if rec is None:
                fails.append(f"conf缺失({p},{o})")
            elif not rec.confidence > v:
                fails.append(f"conf({p},{o})={rec.confidence:.2f}<={v}")

    last = results[-1] if results else None
    got_objs = [m.object for m in last.memories_used] if last else []
    if "recall_contains" in exp:
        for o in exp["recall_contains"]:
            if not any(o in g for g in got_objs):
                fails.append(f"召回缺{o}")
    if "recall_not_contains" in exp:
        for o in exp["recall_not_contains"]:
            if any(o in g for g in got_objs):
                fails.append(f"召回混入{o}")
    if "recall_top" in exp:
        top = got_objs[0] if got_objs else None
        if top != exp["recall_top"]:
            fails.append(f"top1={top}!={exp['recall_top']}")
    if "recall_min" in exp and len(got_objs) < exp["recall_min"]:
        fails.append(f"召回数{len(got_objs)}<{exp['recall_min']}")
    if "ops_last_any" in exp:
        ops = last.ops if last else []
        for want in exp["ops_last_any"]:
            hit = any(
                all(getattr(op, k, None) == v for k, v in want.items()) for op in ops
            )
            if not hit:
                fails.append(f"末轮ops缺{want}")
    if exp.get("reply_nonempty") and (not last or not last.reply):
        fails.append("reply为空")

    return (not fails, "PASS" if not fails else "; ".join(fails))


def main() -> int:
    ap = argparse.ArgumentParser(description="memomind 评测 v2（eval_set_100）")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cases = json.loads((EVALS / "eval_set_100.json").read_text(encoding="utf-8"))
    results = [run_case(c) for c in cases]

    by_layer: dict[str, list[CaseResult]] = {}
    for r in results:
        by_layer.setdefault(r.layer, []).append(r)

    print("=" * 82)
    print(f"memomind 评测 v2（{len(cases)} 条分层用例，确定性 mock 模式）")
    print("=" * 82)
    print(f"{'层':<8}{'用例':>6}{'通过':>6}{'正确率':>9}")
    print("-" * 82)
    total_pass = 0
    for layer, rs in by_layer.items():
        passed = sum(1 for r in rs if r.passed)
        total_pass += passed
        print(f"{layer:<8}{len(rs):>6}{passed:>6}{passed / len(rs):>8.0%}")
        for r in rs:
            mark = "PASS" if r.passed else "FAIL"
            line = f"  {r.sid} {mark}  {r.title}"
            if (args.verbose or not r.passed) and not r.passed:
                line += f"   [{r.detail}]"
            print(line)
    print("-" * 82)
    print(f"{'整体':<8}{len(results):>6}{total_pass:>6}{total_pass / len(results):>8.0%}")
    print("=" * 82)
    print("口径：RuleExtractor + RuleOpsDecider + MockResponder，固定时钟 T0=2026-07-01，无网络；")
    print("用例与期望见 eval_set_100.json（真模型对比只替换抽取器，不改动用例）。")

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1))
    return 0 if total_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
