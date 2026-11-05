"""记忆的可移植层：JSONL 导出/导入 + 图查询 DSL（E 系原创扩展）。

可移植性回答"记忆被锁死在你的 SQLite 里怎么办"：导出 = 全字段 JSONL（含
时间有效性/状态/溯源），导入 = 逐条校验 + 幂等去重（同 id 或同 active 三元组跳过）。
图查询 DSL 让"顺着关系问记忆"成为一行表达式：李雷 -target_role-> * 。
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .schema import MemoryRecord, MemoryStatus
from .store import MemoryStore

_COLS = ("id", "subject", "predicate", "object", "category", "confidence",
         "valid_from", "valid_to", "status", "source_session", "created_at",
         "last_accessed")


# ---------------- 导出 / 导入 ----------------


def export_memories(store: MemoryStore, path: str | Path,
                    include_inactive: bool = False) -> dict[str, int]:
    """全字段导出为 JSONL（默认仅 active；include_inactive=True 连归档/被替代一起导）。

    返回计数。全字段意味着导入端可以完整重建时间线——可移植性不打折。
    """
    status = None if include_inactive else MemoryStatus.ACTIVE.value
    records = store.list(status=status, limit=100000)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(asdict(rec) if hasattr(rec, "__dataclass_fields__")
                               else dict(rec._mapping), ensure_ascii=False, default=str) + "\n")
    return {"exported": len(records)}


def import_memories(store: MemoryStore, path: str | Path, now: Optional[float] = None,
                    dedupe: str = "skip") -> dict[str, int]:
    """从 JSONL 导入记忆，幂等：同 id 或同 active 三元组已存在则跳过。

    dedupe:
      - "skip"（保守默认）：宁可少导不可重导；
      - "update"：同 id 已存在 → 整行覆盖（保留 FTS 触发器语义：显式 DELETE+INSERT），
        同 active 三元组不同 id 仍跳过（身份由三元组定，合并策略属上层）。
    行解析失败计入 invalid_lines 并继续——坏一行不拖垮整批。
    """
    now = store.clock() if now is None else now
    existing_ids = {r.id for r in store.list(status=None, limit=100000)}
    existing_triples = {(r.subject, r.predicate, r.object)
                        for r in store.list(status=MemoryStatus.ACTIVE.value, limit=100000)}
    stats = {"added": 0, "skipped_duplicate": 0, "invalid_lines": 0}
    _status_whitelist = {s.value for s in MemoryStatus}

    def _as_float(value: Any, field: str) -> Any:
        # MM-1 修复：REAL 列吃进字符串会让每次读路径（float 比 str）抛 TypeError——
        # 导入期显式 coerce，坏值按 invalid_line 拦截而非入库毒化。
        if value is None:
            return None
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"{field} 非有限数: {value!r}")
        return v

    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                status = d.get("status", MemoryStatus.ACTIVE.value)
                if status not in _status_whitelist:
                    raise ValueError(f"status 非法: {status!r}")
                rec = MemoryRecord(
                    id=d["id"], subject=d["subject"], predicate=d["predicate"],
                    object=d["object"], category=d.get("category", ""),
                    confidence=float(d.get("confidence", 0.5)),
                    # valid_from 为 NOT NULL 列（store.add 恒填创建时刻）——导入缺省=now，
                    # 缺失曾直接触发 IntegrityError 中断整批（评审 2.0 MM-1 场景之一）
                    valid_from=_as_float(d.get("valid_from", now), "valid_from"),
                    valid_to=_as_float(d.get("valid_to"), "valid_to"),
                    status=status,
                    source_session=d.get("source_session", ""),
                    created_at=_as_float(d.get("created_at", now), "created_at"),
                    last_accessed=_as_float(d.get("last_accessed", now), "last_accessed"),
                )
                if not math.isfinite(rec.confidence):
                    raise ValueError(f"confidence 非有限数: {d.get('confidence')!r}")
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                stats["invalid_lines"] += 1
                continue
            triple = (rec.subject, rec.predicate, rec.object)
            exists_by_id = rec.id in existing_ids
            if exists_by_id:
                if dedupe != "update":
                    stats["skipped_duplicate"] += 1
                    continue
                # 评审边界补全：update 策略=整行覆盖（显式 DELETE+INSERT 触发 FTS 同步）
                try:
                    store.conn.execute("DELETE FROM memory WHERE id = ?", (rec.id,))
                    store.conn.execute(
                        f"INSERT INTO memory ({','.join(_COLS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(getattr(rec, c) for c in _COLS),
                    )
                except sqlite3.Error:
                    # MM-1 修复：DB 层脏行（完整性/约束类）同样计入 invalid_lines 继续，
                    # 兑现「坏一行不拖垮整批」契约——此前 IntegrityError 中断整批且不回滚。
                    stats["invalid_lines"] += 1
                    continue
                stats["updated"] = stats.get("updated", 0) + 1
                existing_triples.add(triple) if rec.status == MemoryStatus.ACTIVE.value else None
                continue
            if rec.status == MemoryStatus.ACTIVE.value and triple in existing_triples:
                stats["skipped_duplicate"] += 1
                continue
            try:
                store.conn.execute(
                    f"INSERT INTO memory ({','.join(_COLS)}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(getattr(rec, c) for c in _COLS),
                )
            except sqlite3.Error:
                stats["invalid_lines"] += 1
                continue
            existing_ids.add(rec.id)
            if rec.status == MemoryStatus.ACTIVE.value:
                existing_triples.add(triple)
            stats["added"] += 1
    # MM-1 修复：整批单事务——循环内不再逐行 commit，结尾统一提交（异常时回滚整批，
    # 避免半批入库的中间态）；坏行已在上层按 invalid_lines 剔除，不影响本事务。
    try:
        store.conn.commit()
    except sqlite3.Error:
        store.conn.rollback()
        raise
    return stats


# ---------------- 图查询 DSL ----------------


class GraphQueryError(ValueError):
    """DSL 语法错误。"""


def _parse_query(expr: str) -> list[dict[str, Any]]:
    """解析 'A -pred-> B -> *'：N 个 "->" = N 跳，每跳 (起点, 谓词?, 终点)；* 通配。"""
    hops = [h.strip() for h in expr.split("->")]
    if len(hops) < 2 or len(hops) > 4 or not all(hops):
        raise GraphQueryError(
            f"图查询语法：实体 -[谓词]-> 实体（1~3 跳，* 为通配），收到：{expr!r}")

    segs: list[dict[str, Any]] = []
    for i, hop in enumerate(hops[:-1]):          # 每个 "->" 一跳
        node, pred = hop, None
        if " -" in hop:
            node, _, pred = hop.partition(" -")
            pred = pred.strip().lstrip("-").strip()
        if not node:
            raise GraphQueryError(f"第 {i + 1} 跳缺少起点实体：{expr!r}")
        nxt = hops[i + 1]
        segs.append({
            "subj": None if node == "*" else node,
            "pred": None if pred in (None, "", "*") else pred,
            "obj": None if nxt == "*" else nxt,
        })
    return segs


def graph_query(store: MemoryStore, expr: str, now: Optional[float] = None) -> list[str]:
    """在记忆图上执行 DSL 查询，返回人读的结果行（带谓词与置信度）。

    示例：
      graph_query(store, "李雷 -target_role-> *")
      graph_query(store, "* -applied_to-> 字节跳动")
      graph_query(store, "李雷 -> * -> *")          # 两跳任意关系
    """
    segs = _parse_query(expr)
    g = store.graph(now)

    def _pred_match(want: Optional[str], actual: str) -> bool:
        # 实体域谓词在图中形如 "application_status:流程结束"——前缀匹配
        return want is None or actual == want or actual.startswith(want + ":")

    results: list[str] = []
    seen: set[tuple] = set()

    def walk(node: str, seg_idx: int, path: list[str]) -> None:
        if seg_idx == len(segs):
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                results.append("  ".join(path))
            return
        seg = segs[seg_idx]
        if seg["subj"] is not None and seg["subj"] != node:
            return
        for _, nxt, data in g.out_edges(node, data=True):
            if seg["obj"] is not None and nxt != seg["obj"]:
                continue
            if seg["pred"] is not None and not _pred_match(seg["pred"], data.get("predicate", "")):
                continue
            walk(nxt, seg_idx + 1,
                 path + [f"{node} -[{data.get('predicate')}|{data.get('confidence', 0):.2f}]-> {nxt}"])

    starts = segs[0]["subj"]
    if starts is None:
        for n in list(g.nodes)[:500]:  # 全图通配给上限，防大图全遍历
            walk(n, 0, [])
    else:
        if starts not in g:
            return []
        walk(starts, 0, [])
    return results
def graph_query(store: MemoryStore, expr: str, now: Optional[float] = None) -> list[str]:
    """在记忆图上执行 DSL 查询，返回人读的结果行（带谓词与置信度）。

    示例：
      graph_query(store, "李雷 -target_role-> *")
      graph_query(store, "* -applied_to-> 字节跳动")
      graph_query(store, "李雷 -> * -> *")          # 两跳任意关系
    """
    segs = _parse_query(expr)
    g = store.graph(now)

    def _pred_match(want: Optional[str], actual: str) -> bool:
        # 实体域谓词在图中形如 "application_status:流程结束"——前缀匹配
        return want is None or actual == want or actual.startswith(want + ":")

    results: list[str] = []
    seen: set[tuple] = set()

    def walk(node: str, seg_idx: int, path: list[str]) -> None:
        if seg_idx == len(segs):
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                results.append("  ".join(path))
            return
        seg = segs[seg_idx]
        if seg["subj"] is not None and seg["subj"] != node:
            return
        for _, nxt, data in g.out_edges(node, data=True):
            if seg["obj"] is not None and nxt != seg["obj"]:
                continue
            if seg["pred"] is not None and not _pred_match(seg["pred"], data.get("predicate", "")):
                continue
            walk(nxt, seg_idx + 1,
                 path + [f"{node} -[{data.get('predicate')}|{data.get('confidence', 0):.2f}]-> {nxt}"])

    starts = segs[0]["subj"]
    if starts is None:
        for n in list(g.nodes)[:500]:  # 全图通配给上限，防大图全遍历
            walk(n, 0, [])
    else:
        if starts not in g:
            return []
        walk(starts, 0, [])
    return results
def graph_query(store: MemoryStore, expr: str, now: Optional[float] = None) -> list[str]:
    """在记忆图上执行 DSL 查询，返回人读的结果行（带谓词与置信度）。

    示例：
      graph_query(store, "李雷 -target_role-> *")
      graph_query(store, "* -applied_to-> 字节跳动")
      graph_query(store, "李雷 -> * -> *")          # 两跳任意关系
    """
    segs = _parse_query(expr)
    g = store.graph(now)

    def _node_match(want: Optional[str], actual: str) -> bool:
        return want is None or want == actual

    def _pred_match(want: Optional[str], actual: str) -> bool:
        return want is None or actual == want or actual.startswith(want + ":")

    results: list[str] = []
    seen: set[tuple] = set()

    def walk(node: str, seg_idx: int, path: list[str]) -> None:
        if seg_idx == len(segs):
            key = tuple(path)
            if key not in seen:
                seen.add(key)
                results.append("  ".join(path))
            return
        seg = segs[seg_idx]
        if not _node_match(seg["subj"], node):
            return
        for _, nxt, data in g.out_edges(node, data=True):
            if seg["obj"] is not None and not _node_match(seg["obj"], nxt):
                continue
            if seg["pred"] is not None and not _pred_match(seg["pred"], data.get("predicate", "")):
                continue
            walk(nxt, seg_idx + 1,
                 path + [f"{node} -[{data.get('predicate')}|{data.get('confidence', 0):.2f}]-> {nxt}"])

    starts = segs[0]["subj"]
    if starts is None:
        for n in list(g.nodes)[:500]:  # 全图通配给上限，防大图全遍历
            walk(n, 0, [])
    else:
        if starts not in g:
            return []
        walk(starts, 0, [])
    return results
