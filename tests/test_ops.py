"""ops.py：决策矩阵全分支（ADD/UPDATE/DELETE/NOOP）+ 冲突键 + LLM 决策器回退。"""

from __future__ import annotations

import httpx
import pytest

from memomind.llm import OpenAICompatibleClient
from memomind.ops import (
    LLMOpsDecider,
    PredicatePolicy,
    RuleOpsDecider,
    conflict_key,
)
from memomind.schema import ExtractedFact, MemoryRecord, OP_ADD, OP_DELETE, OP_NOOP, OP_UPDATE

from conftest import T0


def mk_rec(subject="user", predicate="target_role", obj="后端岗", conf=0.9,
           created_at=T0, rec_id="r1"):
    return MemoryRecord(
        id=rec_id, subject=subject, predicate=predicate, object=obj,
        category="preference", confidence=conf, valid_from=T0, valid_to=None,
        status="active", source_session="s0", created_at=created_at,
        last_accessed=created_at,
    )


def fact(p="target_role", o="Agent岗", conf=0.9, polarity="positive"):
    return ExtractedFact("user", p, o, "preference", conf, polarity=polarity)


# -- 冲突键 -------------------------------------------------------------------
def test_conflict_key_scopes():
    assert conflict_key(fact()) == ("user", "target_role")  # functional
    assert conflict_key(fact(p="application_status", o="字节跳动:submitted")) == (
        "user", "application_status", "字节跳动")  # entity
    assert conflict_key(fact(p="applied_to", o="字节跳动")) == (
        "user", "applied_to", "字节跳动")  # per_object
    # 未知谓词默认 per_object（宁可并存不可误杀）
    assert conflict_key(fact(p="mystery")) == ("user", "mystery", "Agent岗")


# -- 决策矩阵 -----------------------------------------------------------------
def test_matrix_e1_new_fact_adds(decider: RuleOpsDecider):
    ops = decider.decide([fact()], [])
    assert len(ops) == 1 and ops[0].op == OP_ADD


def test_matrix_a0_low_confidence_noop(decider: RuleOpsDecider):
    ops = decider.decide([fact(conf=0.1)], [])
    assert ops[0].op == OP_NOOP and "低置信度" in ops[0].reason


def test_matrix_b2_exact_duplicate_noop(decider: RuleOpsDecider):
    ops = decider.decide([fact(o="后端岗", conf=0.8)], [mk_rec(obj="后端岗", conf=0.9)])
    assert ops[0].op == OP_NOOP and "完全重复" in ops[0].reason


def test_matrix_b1_reinforce_updates_confidence(decider: RuleOpsDecider):
    ops = decider.decide([fact(o="后端岗", conf=0.95)], [mk_rec(obj="后端岗", conf=0.85)])
    assert ops[0].op == OP_UPDATE and ops[0].update_kind == "strengthen"
    assert ops[0].confidence == pytest.approx(0.99)  # max+0.05 被 cap 到 0.99
    assert ops[0].target_id == "r1"


def test_matrix_d1_contradiction_supersedes(decider: RuleOpsDecider):
    ops = decider.decide([fact(o="Agent岗")], [mk_rec(obj="后端岗")])
    assert ops[0].op == OP_UPDATE and ops[0].update_kind == "supersede"
    assert ops[0].target_id == "r1" and ops[0].fact.object == "Agent岗"


def test_matrix_d2_multivalue_coexists(decider: RuleOpsDecider):
    ops = decider.decide(
        [fact(p="applied_to", o="美团")],
        [mk_rec(predicate="applied_to", obj="字节跳动", rec_id="r9")],
    )
    # applied_to 是 per_object 多值谓词：不冲突，直接并存
    assert ops[0].op == OP_ADD


def test_matrix_c1_retraction_deletes_targets(decider: RuleOpsDecider):
    existing = [
        mk_rec(predicate="applied_to", obj="阿里巴巴", rec_id="r1"),
        mk_rec(predicate="application_status", obj="阿里巴巴:submitted", rec_id="r2"),
        mk_rec(predicate="target_role", obj="后端岗", rec_id="r3"),
    ]
    ops = decider.decide(
        [fact(p="withdrawn", o="阿里巴巴", polarity="negative")], existing
    )
    deletes = [op for op in ops if op.op == OP_DELETE]
    adds = [op for op in ops if op.op == OP_ADD]
    assert {d.target_id for d in deletes} == {"r1", "r2"}  # 不波及 target_role
    assert len(adds) == 1 and adds[0].fact.predicate == "withdrawn"


def test_same_turn_self_consistency(decider: RuleOpsDecider):
    """一轮里先'投了X'再'X流程结束'：第二条要能命中第一条（模拟状态）。"""
    facts = [
        fact(p="application_status", o="字节跳动:submitted"),
        fact(p="application_status", o="字节跳动:ended"),
    ]
    ops = decider.decide(facts, [])
    assert [op.op for op in ops] == [OP_ADD, OP_UPDATE]
    assert ops[1].update_kind == "supersede"


def test_entity_scoped_only_conflicts_same_company(decider: RuleOpsDecider):
    """两家公司的状态互不冲突。"""
    ops = decider.decide(
        [fact(p="application_status", o="美团:interviewing")],
        [mk_rec(predicate="application_status", obj="字节跳动:submitted", rec_id="r1")],
    )
    assert ops[0].op == OP_ADD


# -- LLM 决策器 ---------------------------------------------------------------
def _transport_returning(payload: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": payload}}]
        })

    return httpx.MockTransport(handler)


def test_llm_decider_happy_path():
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning(
            '{"decisions":[{"index":0,"op":"UPDATE","target_id":"r1","reason":"矛盾"}]}'
        ),
    )
    ops = LLMOpsDecider(client).decide([fact()], [mk_rec()])
    assert ops[0].op == OP_UPDATE and ops[0].target_id == "r1"


def test_llm_decider_falls_back_on_error():
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning("这不是 JSON"),
    )
    ops = LLMOpsDecider(client).decide([fact(o="Agent岗")], [mk_rec(obj="后端岗")])
    # 回退到规则决策器：矛盾 -> supersede
    assert ops[0].op == OP_UPDATE and ops[0].update_kind == "supersede"


def test_llm_decider_empty_facts_no_call():
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning("should-not-be-called"),
    )
    assert LLMOpsDecider(client).decide([], []) == []


def test_unknown_predicate_defaults_to_per_object(decider: RuleOpsDecider):
    policy = PredicatePolicy()
    ops = decider.decide(
        [ExtractedFact("user", "自定义谓词", "A", "other", 0.9)],
        [mk_rec(predicate="自定义谓词", obj="B", rec_id="r1")],
    )
    assert ops[0].op == OP_ADD  # 不误杀
    assert policy.scope_of("自定义谓词") == "per_object"
