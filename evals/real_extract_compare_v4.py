"""真模型抽取对比 v4（同一 20 条）：混合架构空抽兜底接线后的验收复测。

v4 = MM-3 会话。与 v3（谓词映射层复测，19/20）的差异唯一且可归因：
LLM 抽取器外套 :class:`memomind.extract.HybridExtractor`——LLM 抽取结果
为空时回退 RuleExtractor（开关默认开、事件留痕）。v3 定稿残差 1 条
（W09"滴滴挂了"空抽）正是本接线的验收目标：19/20 → 20/20。

- 对比口径不变：同一 20 条输入、(predicate, object) 集合对比、temperature=0；
  规则端基准、normalize 层、抽取 prompt 全部零改动（词典未增量）。
- HybridExtractor 的事件留痕逐样本落表："兜底"列区分 LLM 自身命中 /
  规则兜底救回 / 双空（疑问句），20/20 的构成可审计。
- 花费账本独立（.real_extract_ledger_v4.json，上限 ¥0.3），usage 实记；
  curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com 绕过本机半死
  系统代理（同 v3，见 EVIDENCE.md 传输层备注）。

运行（项目根目录）：
    ../.venv/Scripts/python.exe evals/real_extract_compare_v4.py
产物：evals/eval_set100_real_compare_v4.md + evals/real_extract_compare_rows_v4.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parents[1]           # memomind/
ROOT = PROJ.parent                                    # 工作区根
sys.path.insert(0, str(PROJ))

from memomind.extract import (  # noqa: E402
    HybridExtractor,
    OpenAICompatibleExtractor,
    RuleExtractor,
)
from memomind.llm import OpenAICompatibleClient  # noqa: E402

PRICE_IN, PRICE_OUT = 4.0, 12.0
CAP_YUAN = 0.3
EVALS = Path(__file__).resolve().parent
LEDGER = EVALS / ".real_extract_ledger_v4.json"
OUT_MD = EVALS / "eval_set100_real_compare_v4.md"
OUT_JSON = EVALS / "real_extract_compare_rows_v4.json"

# 与 v3 完全相同的 20 条输入（顺序也不变，保证同口径可比）
SAMPLES = [
    ("U01", "我想投后端岗"),
    ("U08", "我掌握 Python"),
    ("U10", "我投了美团和快手"),
    ("U16", "我叫王芳，我想投测试岗"),
    ("U17", "我想去广州工作"),
    ("W03", "取消阿里的申请"),
    ("W04", "不想投腾讯了"),
    ("W05", "收到字节的offer"),
    ("W09", "滴滴挂了"),
    ("W15", "我投了腾讯和阿里"),
    ("A01", "我投了字节"),
    ("A04", "我投了字节的Agent岗"),
    ("A05", "投了deepseek"),
    ("A14", "我投了字节跳动"),
    ("D01", "我投了滴滴"),
    ("D16", "我投了美团"),
    ("M01", "我投了字节跳动"),
    ("M02", "我熟悉 Python、FastAPI 和 MySQL"),
    ("M10", "我叫王芳，我投了腾讯"),
    ("M20", "改投后端岗了"),
]


class CurlTransport(httpx.BaseTransport):
    """借 Windows curl(schannel TLS) 转发请求，绕过 OpenSSL 指纹被 RST 的环境问题。

    附带职责：解析响应体里的 usage 并累积到 ``self.usage``（评测账本的实tokens
    来源）；NO_PROXY 显式绕过本机半死系统代理。
    """

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self.usage: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        headers = [x for k, v in request.headers.items()
                   if k.lower() not in ("content-length", "host")
                   for x in ("-H", f"{k}: {v}")]
        env = dict(os.environ)
        env["NO_PROXY"] = "dashscope.aliyuncs.com"
        env["no_proxy"] = "dashscope.aliyuncs.com"
        cmd = ["curl", "-s", "--compressed", "--max-time", str(int(self.timeout)),
               "-X", request.method, str(request.url), *headers,
               "--data-binary", "@-"]
        proc = subprocess.run(cmd, input=request.read(), capture_output=True,
                              timeout=self.timeout + 30, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"curl 传输失败 rc={proc.returncode}: {proc.stderr.decode(errors='replace')[:200]}")
        body = proc.stdout
        try:
            data = json.loads(body)
            if isinstance(data.get("usage"), dict):
                self.usage.append(data["usage"])
        except (json.JSONDecodeError, AttributeError):
            pass
        return httpx.Response(200, content=body,
                              headers={"content-type": "application/json"})


def load_llm_kwargs() -> dict:
    env_file = ROOT / "policy-compass" / ".env"
    vals: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    key = vals.get("LLM_API_KEY", "")
    if not key:
        raise SystemExit("未在 policy-compass/.env 找到 LLM_API_KEY，中止")
    base = (vals.get("LLM_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    model = vals.get("LLM_MODEL") or "deepseek-v4-flash-0731"
    print(f"后端：base={base} model={model} key=***{key[-4:]}")
    return dict(base_url=base, api_key=key, model=model)


def load_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"tokens_in": 0, "tokens_out": 0, "est_cost_yuan": 0.0, "calls": 0,
            "price_assumption": f"¥{PRICE_IN}/M in, ¥{PRICE_OUT}/M out（保守上限）"}


def save_ledger(ledger: dict) -> None:
    ledger["updated_at"] = datetime.now().isoformat(timespec="seconds")
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")


def cost_of(tin: int, tout: int) -> float:
    return tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT


def main() -> int:
    ledger = load_ledger()
    if ledger["est_cost_yuan"] >= CAP_YUAN:
        print(f"花费护栏已触发（est ¥{ledger['est_cost_yuan']:.2f} ≥ ¥{CAP_YUAN}），中止")
        return 1
    kw = load_llm_kwargs()
    transport = CurlTransport()
    client = OpenAICompatibleClient(transport=transport, **kw)
    rule_ex = RuleExtractor()
    llm_ex = OpenAICompatibleExtractor(client)
    hybrid = HybridExtractor(llm_ex)  # 本验收的唯一变量：LLM 抽空 -> 规则兜底

    rows = []
    for sid, text in SAMPLES:
        r_facts = [(f.subject, f.predicate, f.object, round(f.confidence, 2), f.polarity)
                   for f in rule_ex.extract(text, "s", 1000.0)]
        ev_before = len(hybrid.events)
        h_facts = [(f.subject, f.predicate, f.object, round(f.confidence, 2), f.polarity)
                   for f in hybrid.extract(text, "s", 1000.0)]
        raw_facts = [dict(subject=f.subject, predicate=f.predicate, object=f.object,
                          confidence=round(f.confidence, 2), polarity=f.polarity,
                          rule=f.rule)
                     for f in llm_ex.last_raw_facts]

        events = hybrid.events[ev_before:]
        if not events:
            route = "LLM"          # LLM 抽出事实，兜底未触发
        elif events[0]["rescued"]:
            route = "兜底救回"      # LLM 空抽，规则底线救回
        else:
            route = "双空"          # 疑问句/寒暄，两路都无事实

        r_triples = {(p, o) for _, p, o, _, _ in r_facts}
        h_triples = {(p, o) for _, p, o, _, _ in h_facts}
        raw_triples = {(f["predicate"], f["object"]) for f in raw_facts}
        rows.append(dict(sid=sid, text=text, rule=r_facts, hybrid=h_facts,
                         llm_raw=raw_facts, route=route,
                         agree=sorted(r_triples & h_triples),
                         rule_only=sorted(r_triples - h_triples),
                         hybrid_only=sorted(h_triples - r_triples),
                         raw_empty=not raw_facts,
                         exact_match=r_triples == h_triples))
        mark = "完全一致" if r_triples == h_triples else \
            f"一致{len(r_triples & h_triples)} 规则独有{len(r_triples - h_triples)} 混合独有{len(h_triples - r_triples)}"
        print(f"  [{sid}] {mark}  路径={route}")

        # 花费记账（实 tokens）+ 护栏
        if transport.usage:
            u = transport.usage[-1]
            tin, tout = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
            ledger["tokens_in"] += tin
            ledger["tokens_out"] += tout
            ledger["calls"] += 1
            ledger["est_cost_yuan"] = round(
                cost_of(ledger["tokens_in"], ledger["tokens_out"]), 4)
            save_ledger(ledger)
            if ledger["est_cost_yuan"] >= CAP_YUAN:
                print(f"花费护栏触发（¥{ledger['est_cost_yuan']:.2f} ≥ ¥{CAP_YUAN}），停止后续调用")
                break

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(rows)
    exact = sum(1 for r in rows if r["exact_match"])
    n_llm = sum(1 for r in rows if r["route"] == "LLM")
    n_rescued = sum(1 for r in rows if r["route"] == "兜底救回")
    n_both_empty = sum(1 for r in rows if r["route"] == "双空")
    raw_exact = sum(
        1 for r in rows if not r["raw_empty"]
        and {(f["predicate"], f["object"]) for f in r["llm_raw"]}
        == {(p, o) for _, p, o, _, _ in r["rule"]}
    )
    L = [
        "# memomind 真模型抽取对比 v4（同一 20 条，混合架构空抽兜底接线验收）",
        "",
        "- 与 v3 的唯一变量：LLM 抽取器外套 `memomind/extract.py::HybridExtractor`——"
        "LLM 抽取结果为空时回退 RuleExtractor（开关默认开、事件留痕）。"
        "规则端基准、normalize 层词典、抽取 prompt 全部零改动。",
        f"- 花费（usage 实测）：{ledger['calls']} 次调用，"
        f"{ledger['tokens_in']} in + {ledger['tokens_out']} out tokens ≈ "
        f"¥{ledger['est_cost_yuan']:.2f}（本轮上限 ¥{CAP_YUAN}），"
        "单价假设 " + ledger["price_assumption"] + "，账本 evals/.real_extract_ledger_v4.json。",
        "- 传输层：curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com 绕过本机半死系统代理。",
        "",
        "| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 原始 (pred, obj) | 混合输出 (pred, obj) | 一致 | 路径 | 规则独有 | 混合独有 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        rt = "; ".join(f"({p},{o})" for _, p, o, _, _ in r["rule"]) or "无"
        ht = "; ".join(f"({p},{o})" for _, p, o, _, _ in r["hybrid"]) or "无"
        rawt = "; ".join(f"({f['predicate']},{f['object']})" for f in r["llm_raw"]) or "无"
        ro = "; ".join(f"({p},{o})" for p, o in r["rule_only"]) or "-"
        ho = "; ".join(f"({p},{o})" for p, o in r["hybrid_only"]) or "-"
        L.append(f"| {r['sid']} | {r['text']} | {rt} | {rawt} | {ht} | "
                 f"{'√' if r['exact_match'] else '部分'} | {r['route']} | {ro} | {ho} |")
    L += [
        "",
        "## 汇总",
        "",
        f"- 混合架构完全一致：**{exact}/{n} = {exact/n:.0%}**（v3 无兜底 19/20，残差=LLM 空抽）",
        f"- 路径构成：LLM 自身命中 {n_llm}/{n}，规则兜底救回 {n_rescued}/{n}，"
        f"双空（疑问句）{n_both_empty}/{n}",
        f"- LLM 非空且未归一原始输出即完全一致：{raw_exact}/{n}"
        "（原始对照口径，改进仍归因归一化层）",
        "",
        "## 差异分析",
        "",
        "<!-- ANALYSIS_PLACEHOLDER -->",
        "",
    ]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n明细已写入 {OUT_MD} 与 {OUT_JSON}")
    print(f"汇总：混合完全一致 {exact}/{n} = {exact/n:.0%}；"
          f"LLM 命中 {n_llm} 兜底救回 {n_rescued} 双空 {n_both_empty}")
    print(f"花费：¥{ledger['est_cost_yuan']:.2f} / ¥{CAP_YUAN}（{ledger['calls']} 次调用，"
          f"{ledger['tokens_in']}+{ledger['tokens_out']} tokens）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
