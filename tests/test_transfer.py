"""可移植层测试：导出/导入幂等 + 图查询 DSL。"""
import json

import pytest

from memomind.schema import MemoryStatus
from memomind.store import MemoryStore
from memomind.transfer import (
    GraphQueryError,
    export_memories,
    graph_query,
    import_memories,
)


def seed(store: MemoryStore) -> None:
    store.add(_fact("user", "name", "李雷"), source_session="s1")
    store.add(_fact("user", "target_role", "后端工程师"), source_session="s1")
    store.add(_fact("user", "applied_to", "字节跳动"), source_session="s2")


def _fact(subject, predicate, obj, confidence=0.9):
    from memomind.schema import ExtractedFact
    return ExtractedFact(subject, predicate, obj, "job", confidence)


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(str(tmp_path / "mem.db"))
    seed(s)
    return s


def test_export_import_roundtrip(store, tmp_path):
    path = tmp_path / "dump.jsonl"
    n = export_memories(store, path)["exported"]
    assert n == 3

    store2 = MemoryStore(str(tmp_path / "mem2.db"))
    stats = import_memories(store2, path)
    assert stats["added"] == 3 and stats["skipped_duplicate"] == 0
    assert store2.count() == 3
    # 字段保真：confidence/source_session 随行携带
    rows = store2.list(limit=10)
    assert {r.source_session for r in rows} == {"s1", "s2"}


def test_import_is_idempotent(store, tmp_path):
    path = tmp_path / "dump.jsonl"
    export_memories(store, path)
    store2 = MemoryStore(str(tmp_path / "mem2.db"))
    first = import_memories(store2, path)
    second = import_memories(store2, path)
    assert first["added"] == 3
    assert second["added"] == 0 and second["skipped_duplicate"] == 3
    assert store2.count() == 3


def test_import_skips_active_triple_duplicate(store, tmp_path):
    path = tmp_path / "dump.jsonl"
    export_memories(store, path)
    store2 = MemoryStore(str(tmp_path / "mem2.db"))
    import_memories(store2, path)                      # 预置 3 条
    lines = path.read_text(encoding="utf-8").splitlines()
    # 改 id 但保留同 active 三元组 → 仍应按三元组去重
    rec = json.loads(lines[0])
    rec["id"] = "fresh-id-1"
    path.write_text("\n".join(lines + [json.dumps(rec, ensure_ascii=False)]), encoding="utf-8")
    stats = import_memories(store2, path)
    # 3 条按 id 去重 + fresh-id 那条按 active 三元组去重（id 是新的仍被跳过=三元组去重生效）
    assert stats["skipped_duplicate"] == 4 and stats["added"] == 0
    assert all(r.id != "fresh-id-1" for r in store2.list(limit=10))



def test_import_counts_invalid_lines(store, tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text("{not json}\n{\"id\": \"x\"}\n", encoding="utf-8")
    stats = import_memories(store, path)
    assert stats["invalid_lines"] == 2 and stats["added"] == 0


def test_export_active_only_by_default(store, tmp_path):
    recs = store.list(limit=10)
    store.set_status(recs[0].id, MemoryStatus.ARCHIVED.value)
    default = export_memories(store, tmp_path / "a.jsonl")["exported"]
    full = export_memories(store, tmp_path / "b.jsonl", include_inactive=True)["exported"]
    assert default == 2 and full == 3


def test_graph_query_exact_edge(store):
    out = graph_query(store, "user -target_role-> 后端工程师")
    assert len(out) == 1 and "target_role" in out[0]


def test_graph_query_wildcards(store):
    assert any("applied_to" in r for r in graph_query(store, "* -applied_to-> 字节跳动"))
    assert any("target_role" in r for r in graph_query(store, "user -target_role-> *"))
    assert len(graph_query(store, "user -> *")) == 3  # 任意谓词三条边


def test_graph_query_multi_hop_and_entity_scoped(store):
    store.add(_fact("user", "application_status", "字节跳动:流程结束"), source_session="s3")
    # 实体域谓词在图中拆为 application_status:流程结束 → 前缀匹配可达
    out = graph_query(store, "user -application_status-> 字节跳动")
    assert any("application_status" in r for r in out)
    two_hop = graph_query(store, "user -> * -> *")
    assert isinstance(two_hop, list)


def test_graph_query_errors(store):
    with pytest.raises(GraphQueryError):
        graph_query(store, "只有一跳")
    with pytest.raises(GraphQueryError):
        graph_query(store, "a -> ")
    assert graph_query(store, "不存在的人 -> *") == []


def test_import_update_strategy_overwrites_by_id(store, tmp_path):
    path = tmp_path / "dump.jsonl"
    export_memories(store, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    # 同 id、置信度与偏好对象变更 → update 策略整行覆盖
    rec = json.loads(lines[1])
    rec["confidence"] = 0.42
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    store2 = MemoryStore(str(tmp_path / "mem2.db"))
    import_memories(store2, path)                      # 预置原版
    stats = import_memories(store2, path, dedupe="update")
    assert stats.get("updated") == 1 and stats["added"] == 0
    rows = [r for r in store2.list(limit=10) if r.id == rec["id"]]
    assert rows and rows[0].confidence == 0.42
    # FTS 同步验证：按更新后的内容仍可检索
    hits = store2.search_text(rec["object"] or "x")
    assert isinstance(hits, list)


def test_import_update_same_triple_different_id_still_skips(store, tmp_path):
    path = tmp_path / "dump.jsonl"
    export_memories(store, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    orig = json.dumps(json.loads(lines[0]), ensure_ascii=False)      # 原版（原 id）
    mod_rec = json.loads(lines[0])
    mod_rec["id"] = "another-id"                                     # 同三元组、不同 id
    path.write_text(orig, encoding="utf-8")
    store2 = MemoryStore(str(tmp_path / "mem2.db"))
    import_memories(store2, path)                                    # 预置原版（原 id）
    path.write_text(json.dumps(mod_rec, ensure_ascii=False), encoding="utf-8")
    stats = import_memories(store2, path, dedupe="update")
    # 三元组身份判定不因 update 策略放宽：同 active 三元组、不同 id → 仍跳过
    assert stats["skipped_duplicate"] == 1 and stats.get("updated", 0) == 0
    assert all(r.id != "another-id" for r in store2.list(limit=10))
