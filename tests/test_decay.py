"""decay.py：过期归档、指数衰减归档、compaction、参数可配。"""

from __future__ import annotations

from memomind.decay import DecayConfig, compact, effective_confidence, run_decay
from memomind.schema import ExtractedFact, MemoryStatus


def add(store, p="applied_to", o="滴滴", conf=0.9, days_ago_idle=0.0, valid_to=None):
    now = store.clock() - days_ago_idle * 86400
    return store.add(ExtractedFact("user", p, o, "application", conf),
                     source_session="s", now=now, valid_to=valid_to)


def test_effective_confidence_half_life():
    assert effective_confidence(1.0, 0, 30) == 1.0
    assert effective_confidence(1.0, 30, 30) == 0.5   # 一个半衰期减半
    assert effective_confidence(0.9, 120, 30) < 0.15  # 四个半衰期 -> 触发归档阈值


def test_expiry_archives_valid_to_passed(store, clock):
    rec = add(store, valid_to=clock.t + 86400)
    report = run_decay(store, clock.t)  # 未到期
    assert report.expired_archived == 0
    report = run_decay(store, clock.t + 2 * 86400)  # 已到期
    assert report.expired_archived == 1
    assert store.get(rec.id).status == MemoryStatus.ARCHIVED.value


def test_decay_archives_idle_low_confidence(store, clock):
    rec = add(store, conf=0.9, days_ago_idle=120)  # 0.9 * 0.5^4 ≈ 0.056 < 0.15
    report = run_decay(store, clock.t)
    assert report.decay_archived == 1
    assert store.get(rec.id).status == MemoryStatus.ARCHIVED.value


def test_recently_accessed_memory_survives(store, clock):
    rec = add(store, conf=0.9, days_ago_idle=120)
    store.touch(rec.id, clock.t)  # 刚被想起
    report = run_decay(store, clock.t)
    assert report.decay_archived == 0
    assert store.get(rec.id).status == MemoryStatus.ACTIVE.value


def test_decay_never_touches_high_confidence_fresh(store, clock):
    add(store, conf=0.99, days_ago_idle=5)
    run_decay(store, clock.t)
    assert store.count(status="archived") == 0


def test_compaction_purges_old_superseded_but_keeps_fresh(store, clock):
    old = add(store, o="旧公司")
    fresh = add(store, o="新公司")
    store.set_status(old.id, MemoryStatus.SUPERSEDED.value, now=clock.t - 40 * 86400)
    store.set_status(fresh.id, MemoryStatus.SUPERSEDED.value, now=clock.t)
    removed = compact(store, clock.t, DecayConfig(superseded_retention_days=30))
    assert removed == 1
    assert store.get(old.id) is None          # 物理删除
    assert store.get(fresh.id) is not None    # 未超保留期


def test_compaction_purges_old_archived(store, clock):
    rec = add(store)
    store.set_status(rec.id, MemoryStatus.ARCHIVED.value, now=clock.t)
    cfg = DecayConfig(archived_retention_days=90)
    assert compact(store, clock.t + 10 * 86400, cfg) == 0
    assert compact(store, clock.t + 120 * 86400, cfg) == 1
    assert store.get(rec.id) is None


def test_run_decay_idempotent(store, clock):
    add(store, conf=0.5, days_ago_idle=365)
    r1 = run_decay(store, clock.t)
    r2 = run_decay(store, clock.t)
    assert r1.decay_archived == 1 and r2.decay_archived == 0
    assert store.count(status="active") == 0
