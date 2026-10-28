"""遗忘层：指数衰减 + 过期归档 + 定期 compaction。

三种"遗忘"，语义严格区分
--------------------------
1. **过期归档**（expiry）：``valid_to`` 已过 -> status=archived。
   记忆自己声明了有效期（如"在实习，3 个月"），到期自动失效。
2. **衰减归档**（decay）：长期不被想起的记忆，有效置信度按
   ``confidence * 0.5 ** (idle_days / half_life_days)`` 衰减，
   低于 ``min_effective_confidence`` -> archived。"被想起"会刷新
   last_accessed（检索层负责 touch），常用记忆天然抗遗忘。
3. **compaction**（物理清理）：superseded / archived 记忆只是逻辑不可见，
   保留期过后由 compaction 物理删除 —— 逻辑遗忘（决策层/本层前两步）
   与物理遗忘（GC）分层，审计与"反悔"才有空间。

所有参数可配（DecayConfig），``run_decay`` 幂等可重复调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .schema import MemoryStatus
from .store import MemoryStore

__all__ = ["DecayConfig", "DecayReport", "run_decay", "compact", "effective_confidence"]

SECONDS_PER_DAY = 86400.0


def effective_confidence(confidence: float, idle_days: float, half_life_days: float) -> float:
    """指数衰减后的有效置信度（半衰期模型）。"""
    return confidence * 0.5 ** (max(0.0, idle_days) / max(1e-9, half_life_days))


@dataclass
class DecayConfig:
    half_life_days: float = 30.0
    min_effective_confidence: float = 0.15  # 衰减低于此值 -> archived
    superseded_retention_days: float = 30.0  # compaction: superseded 保留期
    archived_retention_days: float = 90.0  # compaction: archived 保留期


@dataclass
class DecayReport:
    expired_archived: int = 0
    decay_archived: int = 0
    compacted: int = 0

    def to_dict(self) -> dict:
        return {
            "expired_archived": self.expired_archived,
            "decay_archived": self.decay_archived,
            "compacted": self.compacted,
        }


def run_decay(
    store: MemoryStore,
    now: Optional[float] = None,
    config: Optional[DecayConfig] = None,
) -> DecayReport:
    """跑一轮遗忘：先过期归档，再衰减归档。返回报告（幂等）。"""
    import time

    now = time.time() if now is None else now
    cfg = config or DecayConfig()
    report = DecayReport()

    # 1) 过期归档：valid_to 已过
    for rec in store.list(status=MemoryStatus.ACTIVE.value, limit=10000):
        if rec.valid_to is not None and now >= rec.valid_to:
            store.set_status(rec.id, MemoryStatus.ARCHIVED.value, now, valid_to=rec.valid_to)
            report.expired_archived += 1

    # 2) 衰减归档：长期未访问 -> 有效置信度低于阈值
    for rec in store.list(status=MemoryStatus.ACTIVE.value, limit=10000):
        idle_days = (now - rec.last_accessed) / SECONDS_PER_DAY
        eff = effective_confidence(rec.confidence, idle_days, cfg.half_life_days)
        if eff < cfg.min_effective_confidence:
            store.set_status(rec.id, MemoryStatus.ARCHIVED.value, now)
            report.decay_archived += 1

    return report


def compact(
    store: MemoryStore,
    now: Optional[float] = None,
    config: Optional[DecayConfig] = None,
) -> int:
    """物理清理超出保留期的 superseded / archived 记忆，返回删除条数。"""
    import time

    now = time.time() if now is None else now
    cfg = config or DecayConfig()
    removed = 0

    for rec in store.list(status=MemoryStatus.SUPERSEDED.value, limit=10000):
        # 以 valid_to（被替代/撤销时刻）为保留期起点，缺省用 created_at
        t0 = rec.valid_to if rec.valid_to is not None else rec.created_at
        if (now - t0) / SECONDS_PER_DAY > cfg.superseded_retention_days:
            store.hard_delete(rec.id)
            removed += 1

    for rec in store.list(status=MemoryStatus.ARCHIVED.value, limit=10000):
        if (now - rec.last_accessed) / SECONDS_PER_DAY > cfg.archived_retention_days:
            store.hard_delete(rec.id)
            removed += 1

    return removed
