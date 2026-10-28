"""混合检索层：词面召回 + 意图映射 + 图邻域扩展 + 时间衰减/置信度加权排序。

排序公式（确定性、无 embedding）
--------------------------------
    base = 词面命中数 * w_fts + 意图命中 * w_intent + 图邻域 * w_graph
    score = base * confidence * 0.5 ** (idle_days / half_life_days)

- 词面召回：store.search_text（FTS5 trigram 为主，LIKE 兜底）。
- 意图映射：问题式 query（"我叫什么名字？"）与记忆文本没有词面交集，
  用一张"疑问意图 -> 谓词"的映射表补上语义缺口 —— 这是确定性系统里
  对 embedding 检索的最低成本近似；接真模型时可整体换成向量召回，
  排序与注入逻辑不变。
- 图扩展：query 命中的实体在记忆图上的一跳邻居记忆也进入候选（via=graph），
  保证"提到字节时，关于字节的历史状态"能被带出来。
- 时间衰减：按 last_accessed 半衰期折减；"被想起"会刷新时钟（store.touch），
  常用记忆天然抗遗忘，与 decay 层的归档阈值呼应。
- 注入预算：top_k 截断后，再按 max_chars 字符预算从前往后保留，
  保证注入块长度可控（LLM 上下文成本上限）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .schema import MemoryRecord
from .store import MemoryStore, text_terms

__all__ = ["RetrievalConfig", "ScoredMemory", "Retriever", "INTENT_PATTERNS"]

import re

# 疑问意图 -> 谓词（顺序即优先级，先匹配先得）
INTENT_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("name", re.compile(r"名字|叫什么|我是谁")),
    ("uses", re.compile(r"技能|会什么|用过什么|技术栈|会哪些|掌握")),
    ("applied_to", re.compile(r"投过|投了哪些|申请过|投递过|投了什么")),
    ("application_status", re.compile(r"流程|进展|状态|结果|面到|挂|offer|Offer")),
    ("target_role", re.compile(r"目标岗位|想投什么|改投|岗位是什么|什么方向|方向是什么")),
    ("prefers", re.compile(r"喜欢|偏好|倾向")),
    ("prefers_city", re.compile(r"城市|去哪|哪儿|哪里")),
    ("works_at", re.compile(r"在哪家|在哪工作|在哪上班|现公司|在职")),
]


@dataclass
class RetrievalConfig:
    top_k: int = 5
    max_chars: int = 1200  # 注入块的字符预算（近似 token 上限）
    half_life_days: float = 30.0
    min_score: float = 0.05
    w_fts: float = 2.0
    w_intent: float = 4.0
    w_graph: float = 3.0
    graph_depth: int = 1
    intent_enabled: bool = True


@dataclass
class ScoredMemory:
    record: MemoryRecord
    score: float
    base: float
    via: list[str] = field(default_factory=list)  # fts / intent / graph


class Retriever:
    def __init__(
        self,
        store: MemoryStore,
        config: Optional[RetrievalConfig] = None,
        clock=None,
        embedder=None,   # A13：可选语义重排器（BaseEmbedding）；None = 现状行为
    ) -> None:
        self.store = store
        self.config = config or RetrievalConfig()
        self.embedder = embedder
        import time

        self.clock = clock or time.time

    # -- 主流程 --------------------------------------------------------------
    def retrieve(self, query: str, now: Optional[float] = None) -> list[ScoredMemory]:
        """混合检索，返回按 score 降序的 top_k 条（并刷新其 last_accessed）。"""
        now = self.clock() if now is None else now
        cfg = self.config
        terms = [t.lower() for t in text_terms(query)]
        if not terms:
            return []

        scores: dict[str, ScoredMemory] = {}

        def add(rec: MemoryRecord, base_part: float, via: str) -> None:
            entry = scores.get(rec.id)
            if entry is None:
                entry = ScoredMemory(record=rec, score=0.0, base=0.0, via=[])
                scores[rec.id] = entry
            entry.base += base_part
            if via not in entry.via:
                entry.via.append(via)

        # 1) 词面召回（FTS5 + LIKE 兜底已在 store.search_text 内合并）
        for rec in self.store.search_text(query, status="active", limit=cfg.top_k * 10):
            hay = f"{rec.subject} {rec.predicate} {rec.object} {rec.category}".lower()
            hits = sum(1 for t in terms if t in hay)
            if hits:
                add(rec, hits * cfg.w_fts, "fts")

        # 2) 意图映射
        if cfg.intent_enabled:
            for predicate, pattern in INTENT_PATTERNS:
                if pattern.search(query):
                    for rec in self.store.list(status="active", limit=10000):
                        if rec.predicate == predicate:
                            add(rec, cfg.w_intent, "intent")

        # 3) 图邻域扩展：query 命中的实体的一跳邻居
        g = self.store.graph(now)
        matched_entities = set()
        for node in g.nodes:
            if node in query or any(t in node.lower() for t in terms):
                matched_entities.add(node)
        seen_edges = set()
        for entity in matched_entities:
            frontier = {entity}
            for _depth in range(max(1, cfg.graph_depth)):
                nxt = set()
                for n in frontier:
                    nxt |= set(g.successors(n)) | set(g.predecessors(n))
                frontier |= nxt
            for u, v, key, data in g.edges(keys=True, data=True):
                if u in frontier or v in frontier:
                    if (u, v, key) in seen_edges:
                        continue
                    seen_edges.add((u, v, key))
                    rec = self.store.get(data.get("memory_id", ""))
                    if rec is not None and rec.is_retrievable(now):
                        add(rec, cfg.w_graph, "graph")

        # 4) 时间衰减 + 置信度加权
        out: list[ScoredMemory] = []
        for entry in scores.values():
            idle_days = max(0.0, (now - entry.record.last_accessed) / 86400.0)
            decay = 0.5 ** (idle_days / cfg.half_life_days)
            entry.score = entry.base * entry.record.confidence * decay
            if entry.score >= cfg.min_score:
                out.append(entry)
        out.sort(key=lambda e: (-e.score, e.record.id))

        # 4.5) 语义重排（A13，可选）：候选文本与查询的余弦相似度加权融合——
        #      无 embedder 时跳过，行为与现状逐字一致；真模型时预计算向量表是生产前提
        if self.embedder and out:
            from .embedding import rerank_by_similarity

            texts = [f"{e.record.subject} {e.record.predicate} {e.record.object}" for e in out]
            base = [e.score for e in out]
            reranked = dict(rerank_by_similarity(query, texts, self.embedder, base))
            for entry in out:
                entry.score = reranked.get(id(entry), entry.score)
            out.sort(key=lambda e: (-e.score, e.record.id))

        # 5) 截断 + 刷新访问时钟（"被想起"重置遗忘时钟）
        top = out[: cfg.top_k]
        for e in top:
            self.store.touch(e.record.id, now)
            e.record.last_accessed = now
        return top

    # -- 注入块渲染 ----------------------------------------------------------
    def render_block(self, memories: list[ScoredMemory], now: Optional[float] = None) -> str:
        """把检索结果渲染成注入 prompt 的记忆块（带来源与时效标注）。"""
        now = self.clock() if now is None else now
        if not memories:
            return ""
        lines = ["# 相关长期记忆（按相关度排序，参考但不要编造）"]
        budget = self.config.max_chars - len(lines[0])
        used = 0
        for e in memories:
            rec = e.record
            line = "- " + rec.render(now)
            if used + len(line) > budget:
                break
            lines.append(line)
            used += len(line)
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)
