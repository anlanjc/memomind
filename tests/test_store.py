"""store.py：SQLite 往返、FTS5 召回、状态迁移、图视图。"""

from __future__ import annotations

from memomind.schema import ExtractedFact, MemoryStatus
from memomind.store import MemoryStore, text_terms


def fact(s="user", p="applied_to", o="字节跳动", c="application", conf=0.9):
    return ExtractedFact(s, p, o, c, conf)


def test_add_and_roundtrip(store: MemoryStore):
    rec = store.add(fact(), source_session="s1")
    got = store.get(rec.id)
    assert got is not None
    assert (got.subject, got.predicate, got.object) == ("user", "applied_to", "字节跳动")
    assert got.status == "active"
    assert got.source_session == "s1"
    assert got.confidence == 0.9


def test_list_filters_by_status(store: MemoryStore):
    a = store.add(fact(), source_session="s1")
    b = store.add(fact(o="美团"), source_session="s1")
    store.set_status(a.id, MemoryStatus.SUPERSEDED.value)
    assert [r.id for r in store.list(status="active")] == [b.id]
    assert [r.id for r in store.list(status="superseded")] == [a.id]
    assert store.count() == 2
    assert store.count(status="active") == 1


def test_supersede_sets_valid_to(store: MemoryStore):
    rec = store.add(fact())
    store.set_status(rec.id, MemoryStatus.SUPERSEDED.value, now=12345.0)
    got = store.get(rec.id)
    assert got.status == "superseded"
    assert got.valid_to == 12345.0
    assert not got.is_retrievable(13000.0)


def test_valid_to_window(store: MemoryStore, clock):
    rec = store.add(fact(), valid_to=clock.t + 100)
    assert rec.is_retrievable(clock.t + 50)
    assert not rec.is_retrievable(clock.t + 200)


def test_fts_recall_chinese_substring(store: MemoryStore):
    store.add(fact())
    store.add(fact(o="美团", p="applied_to"))
    # trigram / LIKE 混合召回：中文子串"字节"应命中字节跳动
    hits = store.search_text("字节")
    assert [r.object for r in hits] == ["字节跳动"]


def test_fts_recall_ascii_and_multi(store: MemoryStore):
    store.add(fact(p="uses", o="Python", c="skill"))
    store.add(fact(p="uses", o="FastAPI", c="skill"))
    store.add(fact(o="字节跳动"))
    hits = store.search_text("Python")
    assert [r.object for r in hits] == ["Python"]
    hits = store.search_text("Python 字节")
    assert {r.object for r in hits} == {"Python", "字节跳动"}


def test_fts_sync_on_update_and_hard_delete(store: MemoryStore):
    rec = store.add(fact(o="老公司"))
    assert len(store.search_text("老公司")) == 1
    store.set_confidence(rec.id, 0.5)  # UPDATE 触发 FTS 同步触发器
    assert len(store.search_text("老公司")) == 1
    store.hard_delete(rec.id)  # DELETE 同步
    assert store.search_text("老公司") == []
    assert store.get(rec.id) is None


def test_touch_updates_last_accessed(store: MemoryStore, clock):
    rec = store.add(fact())
    t0 = rec.last_accessed
    clock.advance(days=3)
    store.touch(rec.id)
    assert store.get(rec.id).last_accessed > t0


def test_text_terms_segmentation():
    terms = text_terms("我叫什么名字？Python3")
    assert "python3" in terms
    assert "什么" in terms  # 中文二元词切分
    assert "名字" in terms


def test_graph_and_subgraph(store: MemoryStore, clock):
    store.add(fact())  # user -applied_to-> 字节跳动
    store.add(fact(p="application_status", o="字节跳动:submitted"))
    store.add(fact(p="uses", o="Python", c="skill"))
    g = store.graph()
    # 实体域谓词的状态并入实体节点，不产生孤立 "字节跳动:submitted" 节点
    assert {"user", "字节跳动", "Python"} <= set(g.nodes)
    status_edges = g.get_edge_data("user", "字节跳动")
    assert any(k.startswith("application_status") for k in
               (d["predicate"] for d in status_edges.values()))
    # 边带记忆溯源属性
    edge = next(iter(g.get_edge_data("user", "Python").values()))
    assert edge["predicate"] == "uses"
    # 时间有效性：过期记忆不在图上
    clock.advance(days=365)
    rec = store.add(fact(p="works_at", o="美团", c="identity"), valid_to=clock.t - 10)
    g2 = store.graph()
    assert "美团" not in g2.nodes
    # 子图一跳：状态记忆（并入实体的边）也在邻域内
    sg = store.subgraph("字节跳动")
    assert set(sg.nodes) == {"user", "字节跳动"}
    assert sg.number_of_edges() == 2
    assert store.subgraph("不存在的实体").number_of_nodes() == 0


def test_persistence_to_file(tmp_path):
    db = tmp_path / "mem.db"
    s1 = MemoryStore(str(db), clock=lambda: 1000.0)
    rec = s1.add(fact(), source_session="s1")
    s1.close()
    s2 = MemoryStore(str(db), clock=lambda: 2000.0)
    got = s2.get(rec.id)
    assert got is not None and got.object == "字节跳动"
    assert len(s2.search_text("字节")) == 1  # FTS 索引随库持久化
    s2.close()


def test_search_text_status_filters_all_or_groups(store: MemoryStore):
    """回归：多词 LIKE 的 OR 组曾缺括号，AND status 只约束最后一个词组，
    superseded 记录经其他词组泄漏进召回（eval_set_100 M11 抓出）。"""
    rec = store.add(fact(o="字节跳动:interviewing", p="application_status"), source_session="s1")
    store.add(fact(o="字节跳动:ended", p="application_status"), source_session="s2")
    store.set_status(rec.id, MemoryStatus.SUPERSEDED.value)
    # 查询含多个 term：'字节' 命中两条，'近况' 只在末尾组——修复前 interviewing 经
    # '字节' 组无过滤泄漏
    hits = store.search_text("字节的近况", status="active")
    objs = [r.object for r in hits]
    assert "字节跳动:ended" in objs
    assert "字节跳动:interviewing" not in objs
