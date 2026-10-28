"""retrieve.py：混合检索排序、时间衰减、意图映射、图扩展、注入预算。"""

from __future__ import annotations

from memomind.retrieve import RetrievalConfig
from memomind.schema import ExtractedFact


def seed(store, s="user", p="applied_to", o="字节跳动", c="application", conf=0.9, days_ago=0.0):
    f = ExtractedFact(s, p, o, c, conf)
    return store.add(f, source_session="seed", now=store.clock() - days_ago * 86400)


def test_empty_store_returns_empty(retriever):
    assert retriever.retrieve("我投了什么公司？") == []


def test_fts_recall_and_ordering(store, retriever, clock):
    seed(store, o="字节跳动", days_ago=1)
    seed(store, o="美团", days_ago=1)
    hits = retriever.retrieve("字节跳动进展如何")
    assert hits and hits[0].record.object == "字节跳动"
    # 召回会刷新 last_accessed
    assert store.get(hits[0].record.id).last_accessed == clock.t


def test_intent_mapping_covers_zero_lexical_overlap(store, retriever):
    """问题与记忆无词面交集时靠意图映射召回。"""
    seed(store, p="name", o="李雷", c="identity", conf=0.99)
    hits = retriever.retrieve("我叫什么名字？")
    assert [h.record.object for h in hits] == ["李雷"]
    assert "intent" in hits[0].via


def test_time_decay_demotes_stale_memories(store, retriever, clock):
    seed(store, o="滴滴", days_ago=120)     # 很久没被访问
    seed(store, o="字节跳动", days_ago=1)
    hits = retriever.retrieve("我投过的公司")
    objs = [h.record.object for h in hits]
    assert "字节跳动" in objs
    assert objs.index("字节跳动") < objs.index("滴滴") if "滴滴" in objs else True


def test_decay_below_threshold_drops_from_results(store, retriever, clock):
    seed(store, o="滴滴", conf=0.5, days_ago=365)  # 衰减到几乎为 0
    hits = retriever.retrieve("我投过的公司")
    assert [h.record.object for h in hits] == []


def test_top_k_and_budget_truncation(store, retriever, clock):
    for i in range(8):
        seed(store, p="prefers", o=f"特征{i}", c="preference", conf=0.8)
    cfg = RetrievalConfig(top_k=3, max_chars=100000)
    r = retriever.__class__(store, cfg, clock=clock)
    hits = r.retrieve("我喜欢什么")
    assert len(hits) == 3
    # 字符预算：注入块不超过上限
    cfg2 = RetrievalConfig(top_k=8, max_chars=120)
    r2 = retriever.__class__(store, cfg2, clock=clock)
    block = r2.render_block(r2.retrieve("我喜欢什么"))
    assert len(block) <= 120 + 1  # 截断留 1 字符余量


def test_render_block_has_source_and_freshness(store, retriever, clock):
    seed(store, o="字节跳动", days_ago=2)
    hits = retriever.retrieve("字节跳动")
    block = retriever.render_block(hits)
    assert "user applied_to 字节跳动" in block
    assert "来源:seed" in block
    assert "置信度0.90" in block
    assert "有效" in block


def test_graph_expansion_brings_related_memories(store, retriever, clock):
    """query 只提到'字节跳动'，其状态记忆（图邻居）也应被带出。"""
    seed(store, o="字节跳动")
    seed(store, p="application_status", o="字节跳动:interviewing")
    hits = retriever.retrieve("字节跳动")
    objs = {h.record.object for h in hits}
    assert {"字节跳动", "字节跳动:interviewing"} <= objs
    assert any("graph" in h.via for h in hits)
