"""评测执行器：跑 20 个脚本化跨会话场景，输出分维度正确率与整体数字。

用法（项目根目录下）：

    python -m evals.run_evals            # 表格输出
    python -m evals.run_evals --json     # 追加 JSON 明细
    python -m evals.run_evals --verbose  # 逐场景断言细节

确定性口径：RuleExtractor + RuleOpsDecider + MockResponder，固定起始时间，
无网络。接真模型时把 ``build_pipeline`` 里的 provider 换成
OpenAICompatibleExtractor / LLMOpsDecider / OpenAIResponder，重跑同一命令即可。
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from dataclasses import asdict, dataclass

from memomind.chat import MemoChat
from memomind.decay import DecayConfig, compact, run_decay
from memomind.extract import RuleExtractor
from memomind.ops import RuleOpsDecider
from memomind.retrieve import RetrievalConfig, Retriever
from memomind.store import MemoryStore

from .scenarios import DAY, SCENARIOS, EvalContext, Scenario, Step

# 固定起始时间（2026-07-01 00:00 UTC），保证评测完全可复现
T0 = datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc).timestamp()


@dataclass
class ScenarioResult:
    sid: str
    dimension: str
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


def run_scenario(sc: Scenario) -> ScenarioResult:
    store = MemoryStore(":memory:")
    chat = build_pipeline(store)
    ctx = EvalContext(store=store)
    now = T0
    for step in sc.steps:
        now += step.advance_days * DAY
        if step.seed is not None:
            subject, predicate, obj, category, conf, valid_to_days = step.seed
            from memomind.schema import ExtractedFact

            fact = ExtractedFact(subject, predicate, obj, category, conf)
            store.add(
                fact,
                source_session="seed",
                now=now,
                valid_to=(now + valid_to_days * DAY) if valid_to_days is not None else None,
            )
        if step.run_decay:
            run_decay(store, now, DecayConfig())
        if step.run_compact:
            compact(store, now, DecayConfig())
        if step.text:
            result = chat.handle(step.session_id, step.text, now=now)
            ctx.results.append(result)
    ctx.now = now
    ok, detail = sc.check(ctx)
    return ScenarioResult(sc.sid, sc.dimension, sc.title, ok, detail)


def main() -> int:
    parser = argparse.ArgumentParser(description="memomind 确定性评测")
    parser.add_argument("--json", action="store_true", help="输出 JSON 明细")
    parser.add_argument("--verbose", action="store_true", help="逐场景打印细节")
    args = parser.parse_args()

    results = [run_scenario(sc) for sc in SCENARIOS]

    # 分维度统计
    by_dim: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_dim.setdefault(r.dimension, []).append(r)

    print("=" * 78)
    print("memomind 评测（20 个脚本化跨会话场景，确定性 mock 模式）")
    print("=" * 78)
    header = f"{'维度':<8}{'场景':<6}{'通过':>6}{'正确率':>10}   说明"
    print(header)
    print("-" * 78)
    total_pass = 0
    for dim, rs in by_dim.items():
        passed = sum(1 for r in rs if r.passed)
        total_pass += passed
        print(f"{dim:<8}{len(rs):<6}{passed:>6}{passed / len(rs):>9.0%}   ")
        for r in rs:
            mark = "PASS" if r.passed else "FAIL"
            line = f"  {r.sid} {mark}  {r.title}"
            if args.verbose or not r.passed:
                line += f"   [{r.detail}]"
            print(line)
    print("-" * 78)
    print(f"{'整体':<8}{len(results):<6}{total_pass:>6}{total_pass / len(results):>9.0%}")
    print("=" * 78)
    print("口径说明：RuleExtractor + RuleOpsDecider + MockResponder，固定时钟，无网络；")
    print("接真模型用同一命令复现（替换 build_pipeline 中的 provider 即可）。")

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))

    return 0 if total_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
