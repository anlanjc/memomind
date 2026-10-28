"""记忆操作决策层 —— 本项目的头号卖点模块（Mem0 范式的核心）。

抽取器产出候选事实后，**并不直接入库**：先由决策器对照现有 active 记忆，
为每条事实产生一个动作：

    ADD / UPDATE / DELETE / NOOP

决策矩阵（RuleOpsDecider，确定性）
----------------------------------
设新事实 f，其"冲突键"key(f) 由谓词策略决定（见 ``PredicatePolicy``），
现有 active 记忆集合 E：

| #  | 条件                                                      | 动作               | 理由字符串                          |
|----|-----------------------------------------------------------|--------------------|-------------------------------------|
| A0 | f.confidence < min_confidence                             | NOOP               | 低置信度，丢弃                      |
| C1 | f 是撤销型（polarity=negative），命中同实体的投递/状态记忆 | DELETE...+ ADD     | 撤销旧记忆；撤销事实本身留档        |
| B1 | 键命中 r 且 (s,p,o) 完全相同，f.confidence 更高           | UPDATE(strengthen) | 重复提及，合并强化置信度            |
| B2 | 键命中 r 且 (s,p,o) 完全相同，置信度不更高                | NOOP               | 完全重复，跳过                      |
| D1 | 键命中 r'（object 不同）且谓词可冲突                      | UPDATE(supersede)  | 矛盾 -> 新事实生效，旧置 superseded |
| D2 | 键命中 r'（object 不同）且谓词多值                        | ADD                | 多值谓词，并存                      |
| E1 | 键无命中                                                  | ADD                | 新事实                              |

冲突键（谁跟谁"可能矛盾"）由 ``PredicatePolicy`` 声明：

- ``functional`` : (subject, predicate)                 —— 单值属性，如 name/target_role/works_at
- ``entity``     : (subject, predicate, entity(object)) —— 状态类按实体分组，如
                   application_status 的 object 是 "字节跳动:submitted"，实体 = 字节跳动
- ``per_object`` : (subject, predicate, object)         —— 多值谓词，永不冲突，
                   如 applied_to / prefers / uses（投多家公司都是真的）

时间线语义：被替代/撤销的记忆**不物理删除**，置 status=superseded 并封口
valid_to=now —— 审计可查、图上消失、检索不可见；物理删除是 decay.compaction
按保留期做的"遗忘"，与"被取代"是两件事。

同轮自洽：一轮话里先"投了X"再"X流程结束"也能正确消解 —— 决策器在
本地模拟状态（simulation overlay）里顺序处理，不依赖数据库即时落库。

``LLMOpsDecider``：把候选事实 + 现有记忆喂给 LLM 要 JSON 决策，任何异常
（网络/解析）都回退到规则决策器 —— 决策层永远不能"挂掉"。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .schema import (
    ExtractedFact,
    MemoryOp,
    MemoryRecord,
    MemoryStatus,
    OP_ADD,
    OP_DELETE,
    OP_NOOP,
    OP_UPDATE,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PredicatePolicy",
    "RuleOpsDecider",
    "LLMOpsDecider",
    "conflict_key",
    "RETRACT_PREDICATES",
]

# 撤销型谓词：object 是被撤销的实体，作用是"失效"相关记忆，而非描述世界
RETRACT_PREDICATES = {"withdrawn"}


@dataclass
class PredicatePolicy:
    """谓词 -> 冲突范围。未知谓词默认 per_object（宁可并存，不可误杀）。"""

    functional: frozenset[str] = frozenset(
        {"name", "target_role", "works_at", "prefers_city", "lives_in"}
    )
    entity_scoped: frozenset[str] = frozenset({"application_status"})
    per_object: frozenset[str] = frozenset(
        {"applied_to", "prefers", "uses", "goal", "event", "other"}
    )

    def scope_of(self, predicate: str) -> str:
        if predicate in self.functional:
            return "functional"
        if predicate in self.entity_scoped:
            return "entity"
        return "per_object"


DEFAULT_POLICY = PredicatePolicy()


def conflict_key(fact_or_record, policy: PredicatePolicy = DEFAULT_POLICY) -> tuple:
    """一条事实/记忆的冲突键。键相同 => 可能互相矛盾，需要决策器裁决。"""
    subject = fact_or_record.subject
    predicate = fact_or_record.predicate
    obj = fact_or_record.object
    scope = policy.scope_of(predicate)
    if scope == "functional":
        return (subject, predicate)
    if scope == "entity":
        return (subject, predicate, obj.split(":", 1)[0])
    return (subject, predicate, obj)


def _sim_record(fact: ExtractedFact) -> MemoryRecord:
    """决策器模拟状态用的临时记录（id 带 sim- 前缀，不落库）。"""
    return MemoryRecord(
        id="sim-" + uuid.uuid4().hex,
        subject=fact.subject,
        predicate=fact.predicate,
        object=fact.object,
        category=fact.category,
        confidence=fact.confidence,
        valid_from=0.0,
        valid_to=None,
        status=MemoryStatus.ACTIVE.value,
        source_session="",
        created_at=0.0,
        last_accessed=0.0,
    )


@dataclass
class RuleOpsDecider:
    """确定性规则决策器。评测/测试/离线演示用它；逻辑是白板重写首选。"""

    policy: PredicatePolicy = field(default_factory=lambda: DEFAULT_POLICY)
    min_confidence: float = 0.30
    reinforce_delta: float = 0.05
    reinforce_cap: float = 0.99

    name = "rule"

    def decide(
        self,
        facts: list[ExtractedFact],
        existing: list[MemoryRecord],
        now: Optional[float] = None,
    ) -> list[MemoryOp]:
        """对一批候选事实顺序决策。``existing`` 必须是当前 active 记忆快照。

        内部维护模拟状态：本轮先 ADD/supersede 的事实会参与本轮后续事实的
        冲突判定，保证单轮内自洽（先投后撤、先说后改）。
        """
        state: list[MemoryRecord] = [
            r for r in existing if r.status == MemoryStatus.ACTIVE.value
        ]
        ops: list[MemoryOp] = []
        for fact in facts:
            one = self._decide_one_inner(fact, state)
            self._advance_state(one, state)
            ops.extend(one)
        return ops

    # -- 单条事实决策 --------------------------------------------------------
    def _decide_one_inner(
        self, fact: ExtractedFact, state: list[MemoryRecord]
    ) -> list[MemoryOp]:
        # A0 低置信度
        if fact.confidence < self.min_confidence:
            return [
                MemoryOp(OP_NOOP, reason=f"低置信度({fact.confidence:.2f})，丢弃", fact=fact)
            ]

        # C1 撤销型事实：失效同实体的投递/状态记忆，并把撤销本身留档
        if fact.polarity == "negative" or fact.predicate in RETRACT_PREDICATES:
            return self._decide_retraction(fact, state)

        key = conflict_key(fact, self.policy)
        same_key = [r for r in state if conflict_key(r, self.policy) == key]
        exact = [
            r for r in same_key if (r.subject, r.predicate, r.object) == fact.triple_key
        ]

        if exact:
            r = max(exact, key=lambda x: x.confidence)
            if fact.confidence > r.confidence + 1e-9:
                new_conf = min(
                    self.reinforce_cap,
                    max(fact.confidence, r.confidence) + self.reinforce_delta,
                )
                # B1 重复提及 -> 强化（UPDATE/strengthen）
                return [
                    MemoryOp(
                        OP_UPDATE,
                        reason="重复提及，合并强化置信度",
                        target_id=r.id,
                        update_kind="strengthen",
                        confidence=new_conf,
                    )
                ]
            # B2 完全重复
            return [MemoryOp(OP_NOOP, reason="完全重复，跳过", fact=fact, target_id=r.id)]

        if same_key:
            # 键相同但 object 不同
            if self.policy.scope_of(fact.predicate) == "per_object":
                # per_object 键已含 object，正常到不了这里；保险兜底为并存
                return [MemoryOp(OP_ADD, reason="多值谓词，并存", fact=fact)]
            old = max(same_key, key=lambda r: r.created_at)  # 冲突对象取最新一条
            # D1 矛盾 -> 新事实生效，旧置 superseded
            return [
                MemoryOp(
                    OP_UPDATE,
                    reason=f"与现有记忆矛盾({old.subject} {old.predicate} {old.object})，新事实生效",
                    fact=fact,
                    target_id=old.id,
                    update_kind="supersede",
                )
            ]

        # E1 全新事实
        return [MemoryOp(OP_ADD, reason="新事实", fact=fact)]

    def _decide_retraction(
        self, fact: ExtractedFact, state: list[MemoryRecord]
    ) -> list[MemoryOp]:
        entity = fact.object.split(":", 1)[0]
        targets = [
            r
            for r in state
            if r.subject == fact.subject
            and (
                (r.predicate == "applied_to" and r.object == entity)
                or (
                    r.predicate == "application_status"
                    and r.object.split(":", 1)[0] == entity
                )
            )
        ]
        ops: list[MemoryOp] = [
            MemoryOp(
                OP_DELETE,
                reason=f"撤销：失效 {r.subject} {r.predicate} {r.object}",
                target_id=r.id,
            )
            for r in targets
        ]
        ops.append(
            MemoryOp(
                OP_ADD,
                reason="撤销事实留档（审计可查）" if targets else "撤销意图（无对应记忆），留档",
                fact=fact,
            )
        )
        return ops

    # -- 模拟状态推进 --------------------------------------------------------
    def _advance_state(self, ops: list[MemoryOp], state: list[MemoryRecord]) -> None:
        for op in ops:
            if op.op == OP_ADD and op.fact is not None:
                state.append(_sim_record(op.fact))
            elif op.op == OP_UPDATE and op.update_kind == "supersede":
                self._remove(state, op.target_id)
                if op.fact is not None:
                    state.append(_sim_record(op.fact))
            elif op.op == OP_DELETE and op.target_id:
                self._remove(state, op.target_id)
            elif op.op == OP_UPDATE and op.update_kind == "strengthen":
                if op.confidence is not None:
                    for r in state:
                        if r.id == op.target_id:
                            r.confidence = op.confidence
                            break

    @staticmethod
    def _remove(state: list[MemoryRecord], target_id: Optional[str]) -> None:
        if target_id is None:
            return
        for i, r in enumerate(state):
            if r.id == target_id:
                state.pop(i)
                return


class LLMOpsDecider:
    """LLM 版决策器：把候选事实与现有记忆交给模型裁决，异常回退规则决策器。"""

    name = "llm"

    SYSTEM_PROMPT = """你是长期记忆系统的操作决策器。给定"候选事实"与"现有记忆"，
为每条候选事实输出一个动作：
- ADD: 全新事实
- UPDATE: 更新现有记忆（矛盾时新事实生效，旧记忆将被标记为 superseded）
- DELETE: 撤销/否定某条现有记忆
- NOOP: 完全重复或无价值
输出严格 JSON（不要 markdown 代码块）：
{"decisions":[{"index":0,"op":"ADD","target_id":null,"reason":"..."}]}"""

    def __init__(self, client, fallback: Optional[RuleOpsDecider] = None) -> None:
        self.client = client
        self.fallback = fallback or RuleOpsDecider()

    def decide(
        self,
        facts: list[ExtractedFact],
        existing: list[MemoryRecord],
        now: Optional[float] = None,
    ) -> list[MemoryOp]:
        if not facts:
            return []
        payload = {
            "candidate_facts": [
                {
                    "index": i,
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object": f.object,
                    "confidence": f.confidence,
                    "polarity": f.polarity,
                }
                for i, f in enumerate(facts)
            ],
            "existing_memories": [
                {
                    "id": r.id,
                    "subject": r.subject,
                    "predicate": r.predicate,
                    "object": r.object,
                    "confidence": r.confidence,
                }
                for r in existing
            ],
        }
        try:
            raw = self.client.chat(
                self.SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False)
            )
            text = raw.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
            data = json.loads(text)
            decisions = data["decisions"]
            ops: list[MemoryOp] = []
            for d in decisions:
                i = int(d["index"])
                f = facts[i]
                op = str(d["op"]).upper()
                if op not in ("ADD", "UPDATE", "DELETE", "NOOP"):
                    raise ValueError(f"未知动作 {op}")
                tid = d.get("target_id")
                if op == "UPDATE" and not tid:
                    # LLM 没指目标 -> 交给规则版定位，保证 UPDATE 语义完整
                    ops.extend(self.fallback.decide([f], existing, now))
                    continue
                ops.append(
                    MemoryOp(
                        op=op,
                        reason=str(d.get("reason", "")),
                        fact=f if op in ("ADD", "UPDATE") else None,
                        target_id=tid,
                        update_kind="supersede" if op == "UPDATE" else "",
                    )
                )
            return ops
        except Exception:  # noqa: BLE001 - 决策层永不失败，回退规则版
            logger.exception("LLM 决策失败，回退规则决策器")
            return self.fallback.decide(facts, existing, now)
