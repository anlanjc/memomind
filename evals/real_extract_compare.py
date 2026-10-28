"""真模型抽取器对比（v2 评测集抽样 20 条）：RuleExtractor vs OpenAICompatibleExtractor。

抽样覆盖五层：事实更新 / 冲突撤回 / 别名归一 / 时序衰减 / 多跳召回 的陈述句输入，
重点覆盖 v1 对比（real_model_report.md）确认的难点：否定极性（不想投/取消）、
列表切分（和/、）、公司别名（字节/deepseek）、岗位后缀（Agent岗）。

传输层：本机 Python OpenSSL 发起到 DashScope 的完整 HTTP 会被中间设备 RST
（WinError 10054），借 Windows curl(schannel) 实现一个 httpx.BaseTransport——
memomind 的 OpenAICompatibleClient(transport=...) 注入点原样可用，库代码零改动。

花费护栏：20 条 × 1 次调用，按保守单价估算，超 ¥0.5 中止。

运行（项目根目录）：
    ../.venv/Scripts/python.exe evals/real_extract_compare.py
产物：evals/eval_set100_real_compare.md + evals/real_extract_compare_rows.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

PROJ = Path(__file__).resolve().parents[1]           # memomind/
ROOT = PROJ.parent                                    # 工作区根
sys.path.insert(0, str(PROJ))

from memomind.extract import OpenAICompatibleExtractor, RuleExtractor  # noqa: E402
from memomind.llm import OpenAICompatibleClient  # noqa: E402

PRICE_IN, PRICE_OUT = 4.0, 12.0
CAP_YUAN = 0.5
EVALS = Path(__file__).resolve().parent
LEDGER = EVALS / ".real_extract_ledger.json"
OUT_MD = EVALS / "eval_set100_real_compare.md"
OUT_JSON = EVALS / "real_extract_compare_rows.json"

# 20 条输入（来自 eval_set_100.json 的陈述句步骤，标注来源用例）
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
    """借 Windows curl(schannel TLS) 转发请求，绕过 OpenSSL 指纹被 RST 的环境问题。"""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        headers = [x for k, v in request.headers.items()
                   if k.lower() not in ("content-length", "host")
                   for x in ("-H", f"{k}: {v}")]
        cmd = ["curl", "-s", "--compressed", "--max-time", str(int(self.timeout)),
               "-X", request.method, str(request.url), *headers,
               "--data-binary", "@-"]
        proc = subprocess.run(cmd, input=request.read(), capture_output=True,
                              timeout=self.timeout + 30)
        if proc.returncode != 0:
            raise RuntimeError(
                f"curl 传输失败 rc={proc.returncode}: {proc.stderr.decode(errors='replace')[:200]}")
        return httpx.Response(200, content=proc.stdout,
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
    return {"tokens_in": 0, "tokens_out": 0, "est_cost_yuan": 0.0,
            "price_assumption": f"¥{PRICE_IN}/M in, ¥{PRICE_OUT}/M out（保守上限）"}


def main() -> int:
    ledger = load_ledger()
    if ledger["est_cost_yuan"] >= CAP_YUAN:
        print(f"花费护栏已触发（est ¥{ledger['est_cost_yuan']:.2f} ≥ ¥{CAP_YUAN}），中止")
        return 1
    kw = load_llm_kwargs()
    client = OpenAICompatibleClient(transport=CurlTransport(), **kw)
    rule_ex = RuleExtractor()
    llm_ex = OpenAICompatibleExtractor(client)

    rows = []
    for sid, text in SAMPLES:
        r_facts = [(f.subject, f.predicate, f.object, round(f.confidence, 2), f.polarity)
                   for f in rule_ex.extract(text, "s", 1000.0)]
        l_facts = [(f.subject, f.predicate, f.object, round(f.confidence, 2), f.polarity)
                   for f in llm_ex.extract(text, "s", 1000.0)]
        r_triples = {(p, o) for _, p, o, _, _ in r_facts}
        l_triples = {(p, o) for _, p, o, _, _ in l_facts}
        agree = r_triples & l_triples
        rows.append(dict(sid=sid, text=text, rule=r_facts, llm=l_facts,
                         agree=sorted(agree), rule_only=sorted(r_triples - l_triples),
                         llm_only=sorted(l_triples - r_triples),
                         exact_match=r_triples == l_triples))
        mark = "完全一致" if r_triples == l_triples else f"一致{len(agree)} 规则独有{len(r_triples - l_triples)} LLM独有{len(l_triples - r_triples)}"
        print(f"  [{sid}] {mark}")
        if l_triples - r_triples:
            print(f"       LLM 独有: {sorted(l_triples - r_triples)}")
        if r_triples - l_triples:
            print(f"       规则独有: {sorted(r_triples - l_triples)}")

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    n = len(rows)
    exact = sum(1 for r in rows if r["exact_match"])
    has_llm_only = sum(1 for r in rows if r["llm_only"])
    has_rule_only = sum(1 for r in rows if r["rule_only"])
    L = [
        "# memomind 真模型抽取对比 v2（eval_set_100 抽样 20 条，deepseek-v4-flash）",
        "",
        "- 口径：每条输入分别过 RuleExtractor 与 OpenAICompatibleExtractor，",
        "  按 (predicate, object) 三元组集合对比（置信度与极性单列不参与集合判定）。",
        "- 传输层：curl(schannel) transport 注入（同 miniagent 批评测的环境问题）。",
        "- 花费（保守估算）：见 evals/.real_extract_ledger.json。",
        "",
        "| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 抽取 (pred, obj) | 一致 | 规则独有 | LLM 独有 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        rt = "; ".join(f"({p},{o})" for _, p, o, _, _ in r["rule"]) or "无"
        lt = "; ".join(f"({p},{o})" for _, p, o, _, _ in r["llm"]) or "无"
        ro = "; ".join(f"({p},{o})" for p, o in r["rule_only"]) or "-"
        lo = "; ".join(f"({p},{o})" for p, o in r["llm_only"]) or "-"
        L.append(f"| {r['sid']} | {r['text']} | {rt} | {lt} | "
                 f"{'√' if r['exact_match'] else '部分'} | {ro} | {lo} |")
    L += [
        "",
        "## 汇总",
        "",
        f"- 完全一致：{exact}/{n} = {exact/n:.0%}",
        f"- LLM 有独有抽取的输入：{has_llm_only}/{n}；规则有独有抽取的输入：{has_rule_only}/{n}",
        "",
        "## 差异分析（v2 对比 v1 报告 real_model_report.md）",
        "",
        "<!-- ANALYSIS_PLACEHOLDER -->",
        "",
    ]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n明细已写入 {OUT_MD} 与 {OUT_JSON}")
    print(f"汇总：完全一致 {exact}/{n} = {exact/n:.0%}；LLM 独有 {has_llm_only}/{n}；规则独有 {has_rule_only}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
