"""extract.py：规则抽取确定性 + OpenAI 兼容抽取器（MockTransport，无网络）+ 混合兜底。"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
import pytest

from memomind.chat import MemoChat
from memomind.extract import (
    BaseExtractor,
    HybridExtractor,
    OpenAICompatibleExtractor,
    RuleExtractor,
    is_question,
)
from memomind.llm import MissingLLMConfigError, OpenAICompatibleClient
from memomind.ops import RuleOpsDecider
from memomind.retrieve import RetrievalConfig, Retriever
from memomind.schema import ExtractedFact
from memomind.store import MemoryStore


# -- 规则抽取器 ---------------------------------------------------------------
def test_extract_applied_produces_two_facts(extractor: RuleExtractor):
    facts = extractor.extract("我投了字节跳动")
    triples = {(f.subject, f.predicate, f.object) for f in facts}
    assert ("user", "applied_to", "字节跳动") in triples
    assert ("user", "application_status", "字节跳动:submitted") in triples


def test_extract_alias_normalization(extractor: RuleExtractor):
    facts = extractor.extract("字节流程结束了")
    assert any(
        f.predicate == "application_status" and f.object == "字节跳动:ended"
        for f in facts
    )


def test_extract_target_role(extractor: RuleExtractor):
    facts = extractor.extract("我想投后端岗")
    assert [(f.predicate, f.object) for f in facts] == [("target_role", "后端岗")]
    facts = extractor.extract("改投 Agent 岗了")
    assert [(f.predicate, f.object) for f in facts] == [("target_role", "Agent岗")]


def test_extract_question_turn_yields_nothing(extractor: RuleExtractor):
    assert extractor.extract("我叫什么名字？") == []
    assert extractor.extract("我投过哪些公司？") == []
    assert is_question("我的目标岗位是什么？")


def test_extract_multiple_companies_and_skills(extractor: RuleExtractor):
    facts = extractor.extract("我投了美团和快手，我熟悉 Python 和 FastAPI，我更喜欢远程办公")
    preds = [(f.predicate, f.object) for f in facts]
    assert ("applied_to", "美团") in preds
    assert ("applied_to", "快手") in preds
    assert ("uses", "Python") in preds
    assert ("uses", "FastAPI") in preds
    assert ("prefers", "远程办公") in preds


def test_extract_withdrawal_negative_polarity(extractor: RuleExtractor):
    facts = extractor.extract("取消阿里的申请")
    assert len(facts) == 1
    assert (facts[0].predicate, facts[0].object) == ("withdrawn", "阿里巴巴")
    assert facts[0].polarity == "negative"


def test_extract_offer_and_interview(extractor: RuleExtractor):
    assert any(f.object == "字节跳动:interviewing"
               for f in extractor.extract("收到字节的面试邀请"))
    assert any(f.object == "字节跳动:offer"
               for f in extractor.extract("收到字节的offer"))


def test_extract_deterministic(extractor: RuleExtractor):
    a = extractor.extract("我投了字节跳动，我想投Agent岗")
    b = extractor.extract("我投了字节跳动，我想投Agent岗")
    assert [(f.subject, f.predicate, f.object, f.confidence) for f in a] == \
           [(f.subject, f.predicate, f.object, f.confidence) for f in b]


# -- OpenAI 兼容抽取器 --------------------------------------------------------
def _llm_transport(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}]
        })

    return httpx.MockTransport(handler)


def test_openai_extractor_parses_facts():
    content = ('```json\n{"facts":[{"subject":"user","predicate":"applied_to",'
               '"object":"字节跳动","category":"application","confidence":0.9}]}\n```')
    ex = OpenAICompatibleExtractor(client=OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_llm_transport(content)))
    facts = ex.extract("我投了字节跳动")
    # 谓词映射层的伴随补全：applied_to 自动带上 application_status:submitted
    assert len(facts) == 2
    assert facts[0].predicate == "applied_to" and facts[0].object == "字节跳动"
    assert (facts[1].predicate, facts[1].object) == ("application_status", "字节跳动:submitted")
    # 原始（未归一）事实留痕
    assert len(ex.last_raw_facts) == 1 and ex.last_raw_facts[0].predicate == "applied_to"


def test_openai_extractor_tolerates_bad_json():
    ex = OpenAICompatibleExtractor(client=OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_llm_transport("模型抽风了，不是JSON")))
    assert ex.extract("我投了字节跳动") == []


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("MEMOMIND_LLM_API_KEY", raising=False)
    with pytest.raises(MissingLLMConfigError) as ei:
        OpenAICompatibleExtractor()
    assert "MEMOMIND_LLM_API_KEY" in str(ei.value)


# -- HybridExtractor：LLM 空抽的规则兜底（混合架构接线） -----------------------
class _StubExtractor(BaseExtractor):
    """确定性桩：永远返回预设事实（默认空 = 模拟 LLM 空抽），无网络。"""

    name = "stub"

    def __init__(self, preset: Optional[list[ExtractedFact]] = None) -> None:
        self.preset = list(preset or [])
        self.calls = 0

    def extract(self, turn, session_id="", now=None):
        self.calls += 1
        return list(self.preset)


class _CountingRule(RuleExtractor):
    """规则兜底计数桩：验证"LLM 非空时不该触发兜底"。"""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def extract(self, turn, session_id="", now=None):
        self.calls += 1
        return super().extract(turn, session_id, now)


def test_hybrid_passthrough_when_llm_returns_facts():
    preset = [ExtractedFact("user", "applied_to", "字节跳动", "application", 0.9)]
    fallback = _CountingRule()
    hy = HybridExtractor(_StubExtractor(preset), fallback=fallback)
    facts = hy.extract("我投了字节跳动")
    assert [(f.predicate, f.object) for f in facts] == [("applied_to", "字节跳动")]
    assert fallback.calls == 0  # LLM 非空，兜底不该被触发
    assert hy.events == []


def test_hybrid_fallback_rescues_on_llm_empty(caplog):
    hy = HybridExtractor(_StubExtractor(), fallback=RuleExtractor())
    with caplog.at_level(logging.WARNING, logger="memomind.extract"):
        facts = hy.extract("我投了字节跳动")
    triples = {(f.predicate, f.object) for f in facts}
    assert ("applied_to", "字节跳动") in triples
    assert ("application_status", "字节跳动:submitted") in triples
    # 事件留痕：触发 + 救回 + 救回的具体事实，可观测
    assert len(hy.events) == 1
    ev = hy.events[0]
    assert ev["fallback_used"] is True and ev["rescued"] is True
    assert ev["turn"] == "我投了字节跳动"
    assert ev["facts"] == [["user", "applied_to", "字节跳动"],
                           ["user", "application_status", "字节跳动:submitted"]]
    assert any("规则兜底救回" in r.message for r in caplog.records)


def test_hybrid_fallback_no_rescue_on_question():
    hy = HybridExtractor(_StubExtractor(), fallback=RuleExtractor())
    assert hy.extract("我叫什么名字？") == []
    assert len(hy.events) == 1
    assert hy.events[0]["rescued"] is False  # 疑问句抽空不是事故，但同样留痕


def test_hybrid_disabled_passthrough_empty():
    fallback = _CountingRule()
    hy = HybridExtractor(_StubExtractor(), fallback=fallback, enabled=False)
    assert hy.extract("我投了字节跳动") == []
    assert fallback.calls == 0
    assert hy.events == []


def test_hybrid_no_merge_on_partial_recall():
    # 边界：LLM 非空但抽得比规则少——不合并混流（保持对比口径可归因）
    preset = [ExtractedFact("user", "applied_to", "字节跳动", "application", 0.9)]
    fallback = _CountingRule()
    hy = HybridExtractor(_StubExtractor(preset), fallback=fallback)
    facts = hy.extract("我投了字节跳动")
    assert len(facts) == 1
    assert fallback.calls == 0
    assert hy.events == []


def test_hybrid_events_accumulate_with_rescued_flag():
    hy = HybridExtractor(_StubExtractor(), fallback=RuleExtractor())
    hy.extract("我投了美团")
    hy.extract("我叫什么名字？")
    hy.extract("我投了快手")
    assert len(hy.events) == 3
    assert [e["rescued"] for e in hy.events] == [True, False, True]


def test_hybrid_wired_into_chat_pipeline(clock):
    store = MemoryStore(":memory:", clock=clock)
    bot = MemoChat(
        store,
        HybridExtractor(_StubExtractor()),  # LLM 全空抽
        ops_decider=RuleOpsDecider(),
        retriever=Retriever(store, RetrievalConfig(), clock=clock),
        clock=clock,
    )
    result = bot.handle("s1", "我投了字节跳动")
    assert result.facts_extracted  # 兜底救回的事实进了管线
    assert any(r.predicate == "applied_to" and r.object == "字节跳动"
               for r in store.list(status="active"))
    store.close()
