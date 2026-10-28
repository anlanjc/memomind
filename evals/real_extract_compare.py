"""真模型抽取器对比 v3（v2 评测集抽样 20 条）：RuleExtractor vs OpenAICompatibleExtractor。

v3 = 谓词映射层（memomind/normalize.py）落地后的复测。与 v2（git 历史）的差异：

- LLM 抽取输出经 normalize_facts 归一成规范谓词；原始输出经
  ``llm_ex.last_raw_facts`` 同步留痕，表中"LLM 原始 / LLM 归一"双列可审计；
- 花费账本按 DashScope 返回的 usage 实tokens 记账（v2 只能估算，且账本
  只读不写——本版每次调用后落盘），超 ¥0.5 上限中止；
- curl 子进程显式注入 NO_PROXY=dashscope.aliyuncs.com（本机系统代理
  127.0.0.1:65533 半死，见 EVIDENCE.md 传输层备注）。

对比口径不变：每条输入分别过 RuleExtractor 与 OpenAICompatibleExtractor，
按 (predicate, object) 三元组集合对比（置信度与极性单列不参与集合判定）。

运行（项目根目录）：
    ../.venv/Scripts/python.exe evals/real_extract_compare.py
产物：evals/eval_set100_real_compare_v3.md + evals/real_extract_compare_rows_v3.json
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

from memomind.extract import OpenAICompatibleExtractor, RuleExtractor  # noqa: E402
from memomind.llm import OpenAICompatibleClient  # noqa: E402

PRICE_IN, PRICE_OUT = 4.0, 12.0
CAP_YUAN = 0.5
EVALS = Path(__file__).resolve().parent
LEDGER = EVALS / ".real_extract_ledger.json"
OUT_MD = EVALS / "eval_set100_real_compare_v3.md"
OUT_JSON = EVALS / "real_extract_compare_rows_v3.json"

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


def transform_tags(raw: list[dict], norm_facts: list) -> list[str]:
    """一行输入触发的归一化改写标签（来自原始/归一双记录的差分）。"""
    from memomind.normalize import _norm_company

    tags: list[str] = []
    if any(nf.rule == "normalize_companion" for nf in norm_facts):
        tags.append("伴随补全")
    raw_preds = {f["predicate"] for f in raw}
    norm_preds = {nf.predicate for nf in norm_facts if nf.rule != "normalize_companion"}
    if (any(nf.rule.startswith("norm:") for nf in norm_facts)
            or raw_preds != norm_preds):
        tags.append("谓词映射")
    if any(f.get("polarity") == "negative"
           and f["predicate"] in ("applied_to", "application_status") for f in raw):
        tags.append("极性修正")
    # 实体归一：原始宾语过别名表后改变（剥成空串的是岗位宾语，不算）
    if any(f["object"] and _norm_company(f["object"]) not in ("", f["object"])
           for f in raw):
        tags.append("实体归一")
    return tags


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

    rows = []
    for sid, text in SAMPLES:
        r_facts = [(f.subject, f.predicate, f.object, round(f.confidence, 2), f.polarity)
                   for f in rule_ex.extract(text, "s", 1000.0)]
        norm_facts = llm_ex.extract(text, "s", 1000.0)
        l_facts = [(f.subject, f.predicate, f.object, round(f.confidence, 2), f.polarity)
                   for f in norm_facts]
        raw_facts = [dict(subject=f.subject, predicate=f.predicate, object=f.object,
                          confidence=round(f.confidence, 2), polarity=f.polarity,
                          rule=f.rule)
                     for f in llm_ex.last_raw_facts]

        r_triples = {(p, o) for _, p, o, _, _ in r_facts}
        l_triples = {(p, o) for _, p, o, _, _ in l_facts}
        agree = r_triples & l_triples
        rows.append(dict(sid=sid, text=text, rule=r_facts, llm=l_facts,
                         llm_raw=raw_facts,
                         tags=transform_tags(raw_facts, norm_facts),
                         agree=sorted(agree), rule_only=sorted(r_triples - l_triples),
                         llm_only=sorted(l_triples - r_triples),
                         exact_match=r_triples == l_triples))
        mark = "完全一致" if r_triples == l_triples else f"一致{len(agree)} 规则独有{len(r_triples - l_triples)} LLM独有{len(l_triples - r_triples)}"
        print(f"  [{sid}] {mark}" + (f"  tags={rows[-1]['tags']}" if rows[-1]['tags'] else ""))

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
    raw_exact = sum(
        1 for r in rows
        if {(f["predicate"], f["object"]) for f in r["llm_raw"]}
        == {(p, o) for _, p, o, _, _ in r["rule"]}
    )
    has_llm_only = sum(1 for r in rows if r["llm_only"])
    has_rule_only = sum(1 for r in rows if r["rule_only"])
    tag_count: dict[str, int] = {}
    for r in rows:
        for t in r["tags"]:
            tag_count[t] = tag_count.get(t, 0) + 1
    L = [
        "# memomind 真模型抽取对比 v3（eval_set_100 抽样 20 条，谓词映射层复测）",
        "",
        f"- 模型与口径：与 v2（`eval_set100_real_compare.md`，git 历史）完全相同——"
        "同一 20 条输入、(predicate, object) 集合对比、temperature=0；"
        "唯一变化是 LLM 抽取输出经 `memomind/normalize.py` 谓词映射层归一，"
        "抽取 prompt 未改动（LLM 行为冻结，改进可归因于归一化层）。",
        "- 表中\"LLM 原始\"列是 last_raw_facts 留痕的未归一输出，"
        "\"LLM 归一\"列才是进 ops 决策矩阵的事实。",
        f"- 花费（usage 实测）：{ledger['calls']} 次调用，"
        f"{ledger['tokens_in']} in + {ledger['tokens_out']} out tokens ≈ "
        f"¥{ledger['est_cost_yuan']:.2f}（上限 ¥{CAP_YUAN}），"
        "单价假设 " + ledger["price_assumption"] + "，账本 evals/.real_extract_ledger.json。",
        f"- 传输层：curl(schannel) transport + NO_PROXY=dashscope.aliyuncs.com 绕过本机半死系统代理。",
        "",
        "| 来源用例 | 输入 | 规则抽取 (pred, obj) | LLM 原始 (pred, obj) | LLM 归一 (pred, obj) | 一致 | 规则独有 | LLM 独有 | 改写标签 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        rt = "; ".join(f"({p},{o})" for _, p, o, _, _ in r["rule"]) or "无"
        lt = "; ".join(f"({p},{o})" for _, p, o, _, _ in r["llm"]) or "无"
        rawt = "; ".join(f"({f['predicate']},{f['object']})" for f in r["llm_raw"]) or "无"
        ro = "; ".join(f"({p},{o})" for p, o in r["rule_only"]) or "-"
        lo = "; ".join(f"({p},{o})" for p, o in r["llm_only"]) or "-"
        tg = "; ".join(r["tags"]) or "-"
        L.append(f"| {r['sid']} | {r['text']} | {rt} | {rawt} | {lt} | "
                 f"{'√' if r['exact_match'] else '部分'} | {ro} | {lo} | {tg} |")
    L += [
        "",
        "## 汇总",
        "",
        f"- 完全一致（归一后）：**{exact}/{n} = {exact/n:.0%}**（v2 修复前 0/20）",
        f"- 完全一致（LLM 原始输出，未归一对照）：{raw_exact}/{n}——"
        "改进全部来自归一化层而非模型行为变化" if raw_exact == 0 else
        f"- 完全一致（LLM 原始输出，未归一对照）：{raw_exact}/{n}",
        f"- 归一后仍有 LLM 独有抽取的输入：{has_llm_only}/{n}；规则独有：{has_rule_only}/{n}",
        f"- 改写标签分布：{json.dumps(tag_count, ensure_ascii=False)}",
        "",
        "## 差异分析",
        "",
        "<!-- ANALYSIS_PLACEHOLDER -->",
        "",
    ]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n明细已写入 {OUT_MD} 与 {OUT_JSON}")
    print(f"汇总：完全一致 {exact}/{n} = {exact/n:.0%}（原始对照 {raw_exact}/{n}）；"
          f"LLM 独有 {has_llm_only}/{n}；规则独有 {has_rule_only}/{n}")
    print(f"花费：¥{ledger['est_cost_yuan']:.2f} / ¥{CAP_YUAN}（{ledger['calls']} 次调用，"
          f"{ledger['tokens_in']}+{ledger['tokens_out']} tokens）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
