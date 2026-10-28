"""空抽兜底活体探针：W09"滴滴挂了"重复 N 次，等待 LLM 空抽被规则兜底救回。

背景：v3 复测 W09 出现过一次空抽（temperature=0 下的召回波动），v4 两轮
20 条都没再抽空——LLM 波动本身波动，兜底路径在评测里未被触发。本探针
用最小成本（同一样本重复 ≤N 次，≈¥0.03）主动捕捉一次活体空抽，验证
HybridExtractor 的事件留痕与救回行为在真实调用下成立（非仅单测桩证据）。

运行（项目根目录）：
    ../.venv/Scripts/python.exe evals/probe_w09_fallback.py
产物：evals/probe_w09_fallback.json（共用 .real_extract_ledger_v4.json 账本）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))

from evals.real_extract_compare_v4 import (  # noqa: E402
    CurlTransport,
    OUT_JSON,
    load_ledger,
    load_llm_kwargs,
    save_ledger,
)
from memomind.extract import (  # noqa: E402
    HybridExtractor,
    OpenAICompatibleExtractor,
    RuleExtractor,
)
from memomind.llm import OpenAICompatibleClient  # noqa: E402

TEXT = "滴滴挂了"          # v3 唯一空抽样本（W09）
MAX_TRIES = 5              # 有界：最多 5 次（≈¥0.03），抓不到就如实报告


def main() -> int:
    kw = load_llm_kwargs()
    transport = CurlTransport()
    client = OpenAICompatibleClient(transport=transport, **kw)
    llm_ex = OpenAICompatibleExtractor(client)
    hybrid = HybridExtractor(llm_ex, RuleExtractor())
    rule_triples = sorted(
        (f.predicate, f.object) for f in RuleExtractor().extract(TEXT, "s", 1000.0)
    )
    ledger = load_ledger()

    tries = []
    for i in range(1, MAX_TRIES + 1):
        ev_before = len(hybrid.events)
        facts = hybrid.extract(TEXT, "s", 1000.0)
        got = sorted((f.predicate, f.object) for f in facts)
        events = hybrid.events[ev_before:]
        rescued = bool(events and events[0]["rescued"])
        tries.append(dict(try_no=i, llm_raw=[(f.predicate, f.object) for f in llm_ex.last_raw_facts],
                          hybrid=[list(t) for t in got], rule=[list(t) for t in rule_triples],
                          rescued=rescued, events=[e["facts"] for e in events],
                          match=got == rule_triples))
        mark = "兜底救回" if rescued else ("LLM 命中" if llm_ex.last_raw_facts else "双空")
        print(f"  try{i}: {mark}  match={got == rule_triples}  raw={tries[-1]['llm_raw']}")
        if transport.usage:
            u = transport.usage[-1]
            ledger["tokens_in"] += int(u.get("prompt_tokens", 0))
            ledger["tokens_out"] += int(u.get("completion_tokens", 0))
            ledger["calls"] += 1
            ledger["est_cost_yuan"] = round(
                ledger["tokens_in"] / 1e6 * 4.0 + ledger["tokens_out"] / 1e6 * 12.0, 4)
            save_ledger(ledger)

    n_rescued = sum(1 for t in tries if t["rescued"])
    n_match = sum(1 for t in tries if t["match"])
    out = dict(text=TEXT, max_tries=MAX_TRIES, tries=tries,
               summary=dict(rescued=n_rescued, all_match=n_match, total=len(tries)))
    probe_path = OUT_JSON.parent / "probe_w09_fallback.json"
    probe_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n汇总：{len(tries)} 次中空抽救回 {n_rescued} 次，与规则基准全匹配 {n_match}/{len(tries)}")
    print(f"证据：{probe_path}；账本累计 ¥{ledger['est_cost_yuan']:.2f}（{ledger['calls']} 次）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
