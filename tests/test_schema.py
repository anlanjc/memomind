"""schema.py：数据模型与时间有效性。"""

from __future__ import annotations

from memomind.schema import (
    ExtractedFact,
    MemoryOp,
    MemoryRecord,
    MemoryStatus,
    OP_ADD,
    OP_UPDATE,
)


def test_record_time_validity():
    rec = MemoryRecord(
        id="x", subject="user", predicate="p", object="o",
        valid_from=100.0, valid_to=200.0,
    )
    assert not rec.is_valid_at(50.0)
    assert rec.is_valid_at(150.0)
    assert not rec.is_valid_at(200.0)  # [from, to) 左闭右开
    open_rec = MemoryRecord(id="y", subject="user", predicate="p", object="o",
                            valid_from=100.0, valid_to=None)
    assert open_rec.is_valid_at(10**12)


def test_record_retrievable_requires_active(store, clock):
    rec = store.add(ExtractedFact("user", "p", "o", "other", 0.9))
    assert rec.is_retrievable(clock.t)
    store.set_status(rec.id, MemoryStatus.ARCHIVED.value)
    assert not store.get(rec.id).is_retrievable(clock.t)


def test_record_roundtrip_dict(store):
    rec = store.add(ExtractedFact("user", "applied_to", "字节跳动", "application", 0.9),
                    source_session="s1")
    clone = MemoryRecord.from_dict(rec.to_dict())
    assert clone == rec


def test_extracted_fact_keys():
    f = ExtractedFact("user", "p", "o", "other", 0.9)
    assert f.key == ("user", "p")
    assert f.triple_key == ("user", "p", "o")


def test_memoryop_str_and_dict():
    op = MemoryOp(OP_ADD, reason="新事实",
                  fact=ExtractedFact("user", "p", "o", "other", 0.9))
    s = str(op)
    assert s.startswith("ADD") and "新事实" in s
    d = op.to_dict()
    assert d["op"] == "ADD" and d["fact"]["object"] == "o"


def test_render_line_has_annotations(store, clock):
    rec = store.add(ExtractedFact("user", "applied_to", "字节跳动", "application", 0.9),
                    source_session="s1")
    line = rec.render(clock.t)
    assert "来源:s1" in line and "置信度0.90" in line and "有效" in line
