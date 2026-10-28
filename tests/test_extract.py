"""extract.py：规则抽取确定性 + OpenAI 兼容抽取器（MockTransport，无网络）。"""

from __future__ import annotations

import httpx
import pytest

from memomind.extract import (
    OpenAICompatibleExtractor,
    RuleExtractor,
    is_question,
)
from memomind.llm import MissingLLMConfigError, OpenAICompatibleClient


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
