"""memomind 的核心数据模型。

本模块只放"纯数据"，不碰 SQLite / networkx / 网络，保证可以单独测试。

三个核心概念
------------
1. ``MemoryRecord``  存储层的一条记忆（主谓宾三元组 + 生命周期字段）。
2. ``ExtractedFact`` 抽取层产出的候选事实（还没有 id，等待 ops 决策）。
3. ``MemoryOp``      操作决策层产出的一条决策（ADD/UPDATE/DELETE/NOOP + 理由）。

记忆生命周期: ``active`` -> (矛盾/撤销/过期) -> ``superseded`` / ``archived``。
superseded = 被新事实替代（逻辑上仍保留用于审计与 compaction 决策）;
archived   = 过期或手动遗忘（不再参与检索）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

__all__ = [
    "MemoryStatus",
    "CATEGORIES",
    "MemoryRecord",
    "ExtractedFact",
    "MemoryOp",
    "OP_ADD",
    "OP_UPDATE",
    "OP_DELETE",
    "OP_NOOP",
]


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


# 记忆类别。category 主要用于检索时的展示与（可选）加权，不参与冲突判定。
CATEGORIES = ("identity", "application", "preference", "skill", "event", "other")

# 操作决策的四种动作（对齐 Mem0 的 ADD/UPDATE/DELETE/NOOP 范式）。
OP_ADD = "ADD"
OP_UPDATE = "UPDATE"
OP_DELETE = "DELETE"
OP_NOOP = "NOOP"


@dataclass
class MemoryRecord:
    """存储层一条记忆 = 一个带时间有效性的三元组断言。

    subject/predicate/object 构成 (谁, 关系, 什么)；
    confidence 是 0~1 的置信度；
    [valid_from, valid_to) 是该断言的时间有效窗口，valid_to=None 表示"一直成立"；
    status 决定它是否参与检索。
    """

    id: str
    subject: str
    predicate: str
    object: str
    category: str = "other"
    confidence: float = 0.8
    valid_from: float = 0.0
    valid_to: Optional[float] = None
    status: str = MemoryStatus.ACTIVE.value
    source_session: str = ""
    created_at: float = 0.0
    last_accessed: float = 0.0

    @property
    def triple(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.object)

    def is_valid_at(self, now: float) -> bool:
        """时间有效性：valid_from <= now < valid_to（valid_to 为空视为长期有效）。"""
        if now < self.valid_from:
            return False
        if self.valid_to is not None and now >= self.valid_to:
            return False
        return True

    def is_retrievable(self, now: float) -> bool:
        """能否参与检索：状态 active 且时间窗口有效。"""
        return self.status == MemoryStatus.ACTIVE.value and self.is_valid_at(now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "status": self.status,
            "source_session": self.source_session,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryRecord":
        return cls(**d)

    def render(self, now: Optional[float] = None) -> str:
        """渲染成注入 prompt 用的一行，带来源与时效标注。"""
        expired = "已过期" if (now is not None and not self.is_valid_at(now)) else "有效"
        return (
            f"{self.subject} {self.predicate} {self.object}"
            f"  [置信度{self.confidence:.2f} | 来源:{self.source_session or '未知'}"
            f" | {expired}]"
        )


@dataclass
class ExtractedFact:
    """抽取层产出的一条候选事实（尚未落库）。

    polarity="negative" 表示这是一条"撤销/否定"性事实（例如"取消阿里的申请"），
    ops 决策器会据此走 DELETE 分支去失效旧记忆，而不是把它当成普通新事实。
    """

    subject: str
    predicate: str
    object: str
    category: str = "other"
    confidence: float = 0.8
    polarity: str = "positive"  # positive | negative
    mentioned_text: str = ""  # 触发抽取的原句片段，用于溯源
    rule: str = ""  # 命中的抽取规则名（RuleExtractor 用）

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject, self.predicate)

    @property
    def triple_key(self) -> tuple[str, str, str]:
        return (self.subject, self.predicate, self.object)

    def to_memory_fields(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "category": self.category,
            "confidence": self.confidence,
        }


@dataclass
class MemoryOp:
    """操作决策层的一条决策。

    - ADD:     新事实落库（fact 必填）。
    - UPDATE:  两种语义，见 ``update_kind``：
               "strengthen"  -> 重复提及，提升 target 指向记忆的置信度；
               "supersede"   -> 矛盾替代，旧记忆置 superseded，新 fact 落库。
    - DELETE:  撤销/失效 target 指向的记忆（置 superseded，不做物理删除，
               物理删除由 decay.compaction 负责）。
    - NOOP:    什么都不做（低置信 / 完全重复），reason 记录原因。
    """

    op: str
    reason: str = ""
    fact: Optional[ExtractedFact] = None
    target_id: Optional[str] = None
    update_kind: str = ""  # strengthen | supersede（仅 UPDATE 用）
    confidence: Optional[float] = None  # strengthen 时的目标置信度

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "reason": self.reason,
            "update_kind": self.update_kind,
            "target_id": self.target_id,
            "fact": None if self.fact is None else {
                "subject": self.fact.subject,
                "predicate": self.fact.predicate,
                "object": self.fact.object,
                "category": self.fact.category,
                "confidence": self.fact.confidence,
            },
        }

    def __str__(self) -> str:  # demo / 日志友好
        if self.op == OP_ADD:
            return f"ADD   {self.fact.subject} {self.fact.predicate} {self.fact.object}  # {self.reason}"
        if self.op == OP_UPDATE:
            return f"UPDATE[{self.update_kind}] target={self.target_id}  # {self.reason}"
        if self.op == OP_DELETE:
            return f"DELETE target={self.target_id}  # {self.reason}"
        return f"NOOP  # {self.reason}"
