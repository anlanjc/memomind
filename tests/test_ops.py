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


# -- LLMOpsDecider 调用统计（事件留痕，MM-3）----------------------------------
def test_llm_decider_stats_normal_path():
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning(
            '{"decisions":[{"index":0,"op":"ADD","target_id":null,"reason":"新"}]}'
        ),
    )
    d = LLMOpsDecider(client)
    d.decide([fact(p="applied_to", o="字节跳动")], [])
    assert d.last_call_stats["mode"] == "llm"
    assert d.last_call_stats["facts"] == 1
    assert d.last_call_stats["decisions"] == 1
    assert d.last_call_stats["delegated_update"] == 0
    assert d.last_call_stats["delegated_retraction"] == 0


def test_llm_decider_stats_update_without_target():
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning(
            '{"decisions":[{"index":0,"op":"UPDATE","target_id":null,"reason":"更新"}]}'
        ),
    )
    d = LLMOpsDecider(client)
    d.decide([fact(o="Agent岗")], [mk_rec(obj="后端岗")])
    assert d.last_call_stats["delegated_update"] == 1


# -- 结构性分支委托规则版（ADR-6：真模型对比发现的系统性分歧）------------------
def test_llm_decider_update_on_exact_triple_delegates():
    # 同三元组重复提及（更高置信）：预路由规则版产出 B1 strengthen，
    # 不进 LLM（真模型对重复提及摇摆于 UPDATE/NOOP 且做不了置信度算术）
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = OpenAICompatibleClient(base_url="http://test", api_key="k", model="m",
                                    transport=httpx.MockTransport(handler))
    d = LLMOpsDecider(client)
    ops = d.decide([ExtractedFact("user", "applied_to", "美团", "application", 0.95)],
                   [mk_rec(predicate="applied_to", obj="美团", conf=0.9)])
    assert calls == []  # 重复提及零 LLM 调用
    assert ops[0].op == OP_UPDATE and ops[0].update_kind == "strengthen"
    assert d.last_call_stats["delegated_repeat"] == 1


def test_llm_decider_exact_repeat_same_conf_is_noop():
    # 同三元组同置信（B2）：预路由后规则版判 NOOP，与矩阵一致
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning("should-not-be-called"),
    )
    d = LLMOpsDecider(client)
    ops = d.decide([ExtractedFact("user", "applied_to", "美团", "application", 0.9)],
                   [mk_rec(predicate="applied_to", obj="美团", conf=0.9)])
    assert ops[0].op == OP_NOOP


def test_llm_decider_retraction_delegates_without_llm_call():
    # 撤销事实是 DELETE(逐条)+ADD(留档) 复合动作，LLM 输出 schema 表达不了
    # （真模型 6/6 分歧）——整体委托规则版，不发起 LLM 调用
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = OpenAICompatibleClient(base_url="http://test", api_key="k", model="m",
                                    transport=httpx.MockTransport(handler))
    d = LLMOpsDecider(client)
    old1 = mk_rec(predicate="applied_to", obj="美团", rec_id="r1")
    old2 = mk_rec(predicate="application_status", obj="美团:submitted", rec_id="r2")
    ops = d.decide([ExtractedFact("user", "withdrawn", "美团", "application",
                                  0.95, polarity="negative")], [old1, old2])
    assert calls == []  # 撤销分支零 LLM 调用
    assert [op.op for op in ops] == [OP_DELETE, OP_DELETE, OP_ADD]
    assert d.last_call_stats["delegated_retraction"] == 1
    assert d.last_call_stats["mode"] == "llm"


def test_llm_decider_mixed_batch_routes_by_polarity():
    # 混合批：正极性事实走 LLM（ADD），撤销事实走规则（DELETE+ADD 留档）
    def handler(request: httpx.Request) -> httpx.Response:
        assert '"index": 0' in request.read().decode()  # 载荷只含正极性事实
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"decisions":[{"index":0,"op":"ADD","target_id":null,"reason":"新投递"}]}'
        }}]})

    client = OpenAICompatibleClient(base_url="http://test", api_key="k", model="m",
                                    transport=httpx.MockTransport(handler))
    d = LLMOpsDecider(client)
    existing = [mk_rec(predicate="applied_to", obj="腾讯", rec_id="r1"),
                mk_rec(predicate="application_status", obj="腾讯:submitted", rec_id="r2")]
    ops = d.decide([ExtractedFact("user", "applied_to", "快手", "application", 0.9),
                    ExtractedFact("user", "withdrawn", "腾讯", "application",
                                  0.95, polarity="negative")], existing)
    kinds = [op.op for op in ops]
    assert kinds.count(OP_ADD) == 2   # LLM 的快手 ADD + 规则的撤销留档 ADD
    assert kinds.count(OP_DELETE) == 2  # 腾讯的两条旧记忆失效
    assert d.last_call_stats["delegated_retraction"] == 1


def test_llm_decider_stats_fallback_error():
    client = OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m",
        transport=_transport_returning("这不是 JSON"),
    )
    d = LLMOpsDecider(client)
    d.decide([fact(o="Agent岗")], [mk_rec(obj="后端岗")])
    assert d.last_call_stats["mode"] == "fallback_error"


def test_llm_decider_lowconf_delegates_without_llm_call():
    # A0 丢弃线是可配置策略阈值（min_confidence），LLM 不知道该配置
    # （真模型把 0.2 置信判 ADD）——预路由规则版丢弃，不进 LLM
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = OpenAICompatibleClient(base_url="http://test", api_key="k", model="m",
                                    transport=httpx.MockTransport(handler))
    d = LLMOpsDecider(client)
    ops = d.decide([ExtractedFact("user", "prefers", "远程办公", "preference", 0.2)], [])
    assert calls == []
    assert ops[0].op == OP_NOOP and "低置信" in ops[0].reason
    assert d.last_call_stats["delegated_lowconf"] == 1
