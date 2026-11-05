"""记忆存储层：SQLite（memory 表 + FTS5 全文索引）+ networkx 图视图。

设计要点
--------
1. 单表 ``memory`` 存三元组断言，字段见 :class:`memomind.schema.MemoryRecord`。
2. FTS5 虚拟表 ``memory_fts`` 做"词面召回"。用 external-content 模式
   （``content='memory'``）+ 触发器与主表保持同步，插入/更新/删除零额外代码。
   tokenizer 优先用 ``trigram``（支持 CJK 子串匹配，SQLite >= 3.34），
   不可用时退回 ``unicode61`` + 前缀查询；两种模式下检索接口行为一致，
   另有 LIKE 兜底保证小词表下 2 字词（如"字节"）也能命中。
3. 图视图是"派生视图"：每次调用 :meth:`MemoryStore.graph` 从当前 active 且
   时间有效的记忆即时构建 networkx.MultiDiGraph，不落盘 —— 记忆是事实，
   图是事实的一种读法（带时间有效性过滤）。
4. 所有写方法接受显式 ``now``（可注入时钟），保证测试与评测完全确定性。
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
import time
import uuid
from typing import Callable, Iterable, Optional

import networkx as nx

from .schema import ExtractedFact, MemoryOp, MemoryRecord, MemoryStatus

__all__ = ["MemoryStore", "fts_tokenizer_mode", "text_terms"]

_COLS = (
    "id, subject, predicate, object, category, confidence, valid_from, valid_to, "
    "status, source_session, created_at, last_accessed"
)


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        category=row["category"],
        confidence=row["confidence"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        status=row["status"],
        source_session=row["source_session"],
        created_at=row["created_at"],
        last_accessed=row["last_accessed"],
    )


# ---------------------------------------------------------------------------
# 查询词切分：ASCII 单词 + 中文连续段（供 LIKE 兜底与 FTS 查询构造）
# ---------------------------------------------------------------------------
_ASCII_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{1,}")
_CJK_SEG = re.compile(r"[\u4e00-\u9fff]{2,}")


def text_terms(text: str) -> list[str]:
    """从用户消息里抽"检索词"：ASCII 词（>=2字符）+ 中文连续段 + 中文二元词。

    中文段整段做 LIKE 兜底命中率低（"字节流程结束了"和库里的"字节跳动"
    没有整段子串交集），补滑窗二元词（字节/流程/结束）后即可词面命中；
    这是确定性系统里对分词器的最低成本替代，接真模型时可换 LLM 抽
    query keywords，接口不变。
    """
    terms: list[str] = []
    for m in _ASCII_WORD.finditer(text):
        w = m.group(0).lower()
        if w not in terms:
            terms.append(w)
    for m in _CJK_SEG.finditer(text):
        seg = m.group(0)
        if seg not in terms:
            terms.append(seg)
        if len(seg) >= 3:
            for i in range(len(seg) - 1):
                bg = seg[i : i + 2]
                if bg not in terms:
                    terms.append(bg)
    return terms


def fts_tokenizer_mode(conn: sqlite3.Connection) -> str:
    """探测 FTS5 可用的 tokenizer（trigram 优先）。"""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _probe_fts "
            "USING fts5(x, tokenize='trigram')"
        )
        conn.execute("DROP TABLE IF EXISTS _probe_fts")
        return "trigram"
    except sqlite3.OperationalError:  # pragma: no cover - 老 SQLite 才走这里
        return "unicode61"


def _fts_query_for(mode: str, terms: Iterable[str]) -> str:
    """把检索词翻成 FTS5 MATCH 表达式。

    - trigram: 用 >=3 字的滑窗 3-gram 做 OR（2 字词交给 LIKE 兜底）。
    - unicode61: 中文段是整 token，用前缀查询 term*（同样由 LIKE 兜底）。
    """
    parts: list[str] = []
    for t in terms:
        if mode == "trigram":
            seg = t if not t[0].isascii() else t
            if len(seg) >= 3:
                for i in range(len(seg) - 2):
                    g = seg[i : i + 3]
                    parts.append('"%s"' % g.replace('"', '""'))
            elif len(seg) == 2 and seg.isascii():
                parts.append('"%s*"' % seg.replace('"', '""'))
        else:  # unicode61
            parts.append('"%s*"' % t.replace('"', '""'))
    # 去重保持顺序
    seen: set[str] = set()
    uniq = [p for p in parts if not (p in seen or seen.add(p))]
    return " OR ".join(uniq)


class MemoryStore:
    """SQLite 记忆库。``db_path=':memory:'`` 用于测试，默认落盘文件。"""

    def __init__(
        self,
        db_path: str = ":memory:",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = db_path
        self.clock = clock
        # check_same_thread=False：FastAPI 线程池会跨线程访问同一连接。
        # MM-5 勘误（评审 2.0）：文件锁不约束进程内共享连接，「单写者=安全」表述已删——
        # 写路径竞态待 MM-5 加锁修复，此处先如实不再断言安全。
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")  # MM-2 修复：写锁等待而非立即 OperationalError
        self._in_txn = False  # MM-2：批级事务抑制内部写方法的逐个 commit
        self._fts_mode = fts_tokenizer_mode(self.conn)
        self._init_schema()

    @contextlib.contextmanager
    def transaction(self):
        """MM-2 修复（评审 2.0 high）：批级显式事务——内部写方法的 commit 被抑制，
        退出时统一提交；异常回滚整批。supersede 的「旧封口+新落库」由此原子化，
        中途失败不再永久丢记忆。"""
        if self.conn.in_transaction:
            self.conn.commit()  # 先收尾隐式事务，避免 BEGIN 撞车
        self._in_txn = True
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()
        finally:
            self._in_txn = False

    def _commit(self) -> None:
        if not self._in_txn:
            self.conn.commit()

    # -- schema ------------------------------------------------------------
    def _init_schema(self) -> None:
        c = self.conn
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id            TEXT PRIMARY KEY,
                subject       TEXT NOT NULL,
                predicate     TEXT NOT NULL,
                object        TEXT NOT NULL,
                category      TEXT NOT NULL DEFAULT 'other',
                confidence    REAL NOT NULL DEFAULT 0.8,
                valid_from    REAL NOT NULL DEFAULT 0,
                valid_to      REAL,
                status        TEXT NOT NULL DEFAULT 'active'
                              CHECK (status IN ('active','archived','superseded')),
                source_session TEXT NOT NULL DEFAULT '',
                created_at    REAL NOT NULL DEFAULT 0,
                last_accessed REAL NOT NULL DEFAULT 0
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_status ON memory(status)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory(subject)"
        )
        c.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                subject, predicate, object, category,
                content='memory', content_rowid='rowid',
                tokenize='{self._fts_mode}'
            )
            """
        )
        c.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory BEGIN
                INSERT INTO memory_fts(rowid, subject, predicate, object, category)
                VALUES (new.rowid, new.subject, new.predicate, new.object, new.category);
            END
            """
        )
        c.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, subject, predicate, object, category)
                VALUES ('delete', old.rowid, old.subject, old.predicate, old.object, old.category);
            END
            """
        )
        c.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory BEGIN
                INSERT INTO memory_fts(memory_fts, rowid, subject, predicate, object, category)
                VALUES ('delete', old.rowid, old.subject, old.predicate, old.object, old.category);
                INSERT INTO memory_fts(rowid, subject, predicate, object, category)
                VALUES (new.rowid, new.subject, new.predicate, new.object, new.category);
            END
            """
        )
        c.commit()

    def close(self) -> None:
        self.conn.close()

    # -- 写 ------------------------------------------------------------------
    def add(
        self,
        fact: ExtractedFact,
        source_session: str = "",
        now: Optional[float] = None,
        valid_to: Optional[float] = None,
        confidence: Optional[float] = None,
    ) -> MemoryRecord:
        """把一条候选事实落为 active 记忆。"""
        now = self.clock() if now is None else now
        rec = MemoryRecord(
            id=uuid.uuid4().hex,
            subject=fact.subject,
            predicate=fact.predicate,
            object=fact.object,
            category=fact.category,
            confidence=float(fact.confidence if confidence is None else confidence),
            valid_from=now,
            valid_to=valid_to,
            status=MemoryStatus.ACTIVE.value,
            source_session=source_session,
            created_at=now,
            last_accessed=now,
        )
        self.conn.execute(
            f"INSERT INTO memory ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec.id, rec.subject, rec.predicate, rec.object, rec.category,
                rec.confidence, rec.valid_from, rec.valid_to, rec.status,
                rec.source_session, rec.created_at, rec.last_accessed,
            ),
        )
        self._commit()
        return rec

    def touch(self, memory_id: str, now: Optional[float] = None) -> None:
        """命中检索时刷新 last_accessed（"被想起"会重置遗忘时钟）。"""
        now = self.clock() if now is None else now
        self.conn.execute(
            "UPDATE memory SET last_accessed = ? WHERE id = ?", (now, memory_id)
        )
        self._commit()

    def set_confidence(self, memory_id: str, confidence: float) -> None:
        self.conn.execute(
            "UPDATE memory SET confidence = ? WHERE id = ?", (confidence, memory_id)
        )
        self._commit()

    def set_status(
        self,
        memory_id: str,
        status: str,
        now: Optional[float] = None,
        valid_to: Optional[float] = ...,  # type: ignore[assignment]
    ) -> None:
        """状态迁移。superseded / archived 时默认把 valid_to 封口到 now。"""
        now = self.clock() if now is None else now
        if valid_to is ...:
            valid_to = (
                now if status in (MemoryStatus.SUPERSEDED.value, MemoryStatus.ARCHIVED.value)
                else None
            )
        self.conn.execute(
            "UPDATE memory SET status = ?, valid_to = ? WHERE id = ?",
            (status, valid_to, memory_id),
        )
        self._commit()

    def hard_delete(self, memory_id: str) -> None:
        """物理删除（仅 compaction 使用；AFTER DELETE 触发器同步 FTS）。"""
        self.conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
        self._commit()

    def apply_ops(
        self, ops: Iterable[MemoryOp], source_session: str = "", now: Optional[float] = None
    ) -> list[dict]:
        """执行操作决策层的一批决策，返回执行日志（供 API / demo 展示）。

        MM-2 修复（评审 2.0 high）：整批显式事务（BEGIN IMMEDIATE…COMMIT，异常回滚）——
        此前逐动作独立提交零回滚，supersede 中途失败（如 confidence='高' 触发
        ValueError）曾永久丢记忆。
        """
        now = self.clock() if now is None else now
        log: list[dict] = []
        with self.transaction():
            for op in ops:
                entry = {"op": op.op, "reason": op.reason, "update_kind": op.update_kind}
                if op.op == "ADD" and op.fact is not None:
                    rec = self.add(op.fact, source_session=source_session, now=now)
                    entry["memory_id"] = rec.id
                    entry["memory"] = rec.to_dict()
                elif op.op == "UPDATE":
                    if op.update_kind == "strengthen" and op.target_id:
                        if op.confidence is not None:
                            self.set_confidence(op.target_id, op.confidence)
                        self.touch(op.target_id, now)
                        entry["memory_id"] = op.target_id
                    elif op.update_kind == "supersede":
                        if op.target_id:
                            self.set_status(op.target_id, MemoryStatus.SUPERSEDED.value, now)
                        if op.fact is not None:
                            rec = self.add(op.fact, source_session=source_session, now=now)
                            entry["memory_id"] = rec.id
                            entry["memory"] = rec.to_dict()
                elif op.op == "DELETE" and op.target_id:
                    self.set_status(op.target_id, MemoryStatus.SUPERSEDED.value, now)
                    entry["memory_id"] = op.target_id
                log.append(entry)
        return log

    # -- 读 ------------------------------------------------------------------
    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        row = self.conn.execute(
            f"SELECT {_COLS} FROM memory WHERE id = ?", (memory_id,)
        ).fetchone()
        return _row_to_record(row) if row else None

    def list(
        self,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        limit: int = 500,
    ) -> list[MemoryRecord]:
        sql = f"SELECT {_COLS} FROM memory"
        conds, args = [], []
        if status:
            conds.append("status = ?")
            args.append(status)
        if subject:
            conds.append("subject = ?")
            args.append(subject)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC, id LIMIT ?"
        args.append(limit)
        return [_row_to_record(r) for r in self.conn.execute(sql, args)]

    def list_active(self, now: Optional[float] = None) -> list[MemoryRecord]:
        """状态 active 且时间窗口有效的记忆（ops 决策与图构建的输入）。"""
        now = self.clock() if now is None else now
        return [
            r
            for r in self.list(status=MemoryStatus.ACTIVE.value, limit=10000)
            if r.is_valid_at(now)
        ]

    def search_text(
        self, query: str, status: Optional[str] = MemoryStatus.ACTIVE.value, limit: int = 50
    ) -> list[MemoryRecord]:
        """词面召回：FTS5 为主、LIKE 兜底，命中数多的排前面（确定性）。

        FTS5 负责长词/3字以上中文子串的高效召回；"字节"这类 2 字中文词
        在 trigram 下无 3-gram，由 LIKE 扫描兜底。结果按 (命中词数, id)
        排序保证确定性。
        """
        terms = text_terms(query)
        if not terms:
            return []
        scores: dict[str, int] = {}

        fts_sql = _fts_query_for(self._fts_mode, terms)
        if fts_sql:
            base = (
                "SELECT m.id AS id FROM memory_fts f JOIN memory m ON m.rowid = f.rowid "
                "WHERE memory_fts MATCH ?"
            )
            if status:
                base += " AND m.status = ?"
                args: list = [fts_sql, status]
            else:
                args = [fts_sql]
            for row in self.conn.execute(base + " LIMIT ?", (*args, limit * 5)):
                scores[row["id"]] = scores.get(row["id"], 0) + 2

        like_conds = " OR ".join(
            ["(subject LIKE ? OR predicate LIKE ? OR object LIKE ? OR category LIKE ?)"] * len(terms)
        )
        like_args: list = []
        for t in terms:
            pat = f"%{t}%"
            like_args += [pat, pat, pat, pat]
        # 整个 OR 组必须加括号：AND 优先级高于 OR，不加括号时 status 只约束
        # 最后一个词组，其余词组命中的 superseded/archived 记录会泄漏进召回
        sql = f"SELECT id FROM memory WHERE ({like_conds})"
        if status:
            sql += " AND status = ?"
            like_args.append(status)
        sql += " LIMIT ?"
        like_args.append(limit * 5)
        for row in self.conn.execute(sql, like_args):
            scores[row["id"]] = scores.get(row["id"], 0) + 1

        ranked_ids = sorted(scores, key=lambda i: (-scores[i], i))[:limit]
        out = [self.get(i) for i in ranked_ids]
        return [r for r in out if r is not None]

    def count(self, status: Optional[str] = None) -> int:
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM memory WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM memory").fetchone()
        return int(row["n"])

    # -- 图视图 ---------------------------------------------------------------
    # 实体域谓词：object 形如 "实体:状态"，构图时拆开——边指向实体节点，
    # 状态并入谓词标签。否则 "字节跳动:submitted" 会成为孤立节点，
    # 实体的一跳邻居里反而看不到自己的状态记忆。
    ENTITY_SCOPED_PREDICATES = {"application_status"}

    def graph(self, now: Optional[float] = None) -> nx.MultiDiGraph:
        """从 active 且时间有效的记忆构建实体关系图（派生视图，不落盘）。

        节点 = subject / object（实体域谓词的 object 拆到实体）；
        边 = 一条记忆，带 predicate / memory_id / category / confidence /
        valid_from / valid_to / source_session 属性。
        """
        now = self.clock() if now is None else now
        g = nx.MultiDiGraph()
        for rec in self.list_active(now):
            subject, predicate, obj = rec.subject, rec.predicate, rec.object
            if rec.predicate in self.ENTITY_SCOPED_PREDICATES and ":" in obj:
                entity, state = obj.split(":", 1)
                predicate = f"{rec.predicate}:{state}"
                obj = entity
            g.add_node(subject)
            g.add_node(obj)
            g.add_edge(
                subject,
                obj,
                key=rec.id,
                predicate=predicate,
                memory_id=rec.id,
                category=rec.category,
                confidence=rec.confidence,
                valid_from=rec.valid_from,
                valid_to=rec.valid_to,
                source_session=rec.source_session,
            )
        return g

    def subgraph(
        self, entity: str, depth: int = 1, now: Optional[float] = None
    ) -> nx.MultiDiGraph:
        """某实体的关系子图（BFS 扩展 depth 跳）。实体不存在返回空图。"""
        g = self.graph(now)
        if entity not in g:
            return nx.MultiDiGraph()
        nodes = {entity}
        frontier = {entity}
        for _ in range(max(0, depth)):
            nxt: set[str] = set()
            for n in frontier:
                nxt |= set(g.successors(n)) | set(g.predecessors(n))
            nodes |= nxt
            frontier = nxt - nodes if nxt else set()
            nodes |= nxt
        return g.subgraph(nodes).copy()
