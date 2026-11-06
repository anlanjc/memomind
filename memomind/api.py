"""FastAPI 服务：把记忆系统暴露成 HTTP API + 单文件记忆浏览器页。

路由
----
- ``POST /chat``            一轮对话（走完整 retrieve->respond->extract->ops->store 管线）
- ``GET  /memories``        记忆列表，支持 ``status`` / ``subject`` / ``q`` 过滤
- ``POST /forget``          手动遗忘（按 memory_id 归档）
- ``GET  /graph/{entity}``  实体记忆子图 JSON（nodes/edges）
- ``POST /maintenance``     手动触发 decay+compaction（运维用，评测脚本也用）
- ``GET  /``                static/index.html 单文件记忆浏览器（无外部依赖）

工厂函数 ``create_app(db_path=...)``：测试传 ``:memory:``，生产传文件路径。
"""

from __future__ import annotations

import math
import threading
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .chat import MemoChat, OpenAIResponder
from .decay import DecayConfig, compact, run_decay
from .extract import HybridExtractor, OpenAICompatibleExtractor, RuleExtractor
from .llm import LLMConfig, MockResponder
from .ops import LLMOpsDecider, RuleOpsDecider
from .retrieve import RetrievalConfig, Retriever
from .schema import MemoryStatus
from .store import MemoryStore

__all__ = ["create_app"]

_STATIC_DIR = Path(__file__).parent / "static"


# -- 请求/响应模型 -----------------------------------------------------------
class ChatRequest(BaseModel):
    # MM-4 纵深：字符集白名单（曾仅限长度，<img onerror> 可经 source_session 透出落库）
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    memories_used: list[dict]
    facts_extracted: list[dict]
    ops: list[dict]


class ForgetRequest(BaseModel):
    memory_id: str = Field(min_length=1)


class MaintenanceRequest(BaseModel):
    run_decay: bool = True
    run_compact: bool = True
    # MM-3 修复（评审 2.0 high）：无下界曾使 half_life_days=0 一次请求静默归档全库——
    # decay 层把 0/负/NaN 钳成 1e-9 而非拒绝，所有 idle>0 记忆 eff≈0 全部归档。
    # 输入即拒绝（gt=0 + 拒 NaN/Inf），把静默钳位改为显式 422。
    half_life_days: float = Field(default=30.0, gt=0)

    @field_validator("half_life_days")
    @classmethod
    def _reject_non_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("half_life_days 必须为有限正数")
        return v


def _build_responder():
    """有 LLM key 且配置成功 -> 真模型（抽取+决策+应答），否则全确定性的 Mock。"""
    try:
        client = None
        try:
            cfg = LLMConfig.from_env()
            from .llm import OpenAICompatibleClient

            client = OpenAICompatibleClient(
                base_url=cfg.base_url, api_key=cfg.api_key, model=cfg.model
            )
        except Exception:
            return MockResponder(), RuleExtractor(), RuleOpsDecider()
        return (
            OpenAIResponder(client),
            HybridExtractor(OpenAICompatibleExtractor(client=client)),
            LLMOpsDecider(client),
        )
    except Exception:
        return MockResponder(), RuleExtractor(), RuleOpsDecider()


# MM-7：/chat 全局并发闸（真模型慢链路背压）
_CHAT_SEM = threading.Semaphore(8)


def create_app(
    db_path: Optional[str] = None,
    retrieval_config: Optional[RetrievalConfig] = None,
) -> FastAPI:
    db_path = db_path or os.environ.get("MEMOMIND_DB", "memomind.db")
    store = MemoryStore(db_path)
    responder, extractor, ops_decider = _build_responder()
    retriever = Retriever(store, retrieval_config or RetrievalConfig())
    chat = MemoChat(
        store,
        extractor,
        ops_decider=ops_decider,
        retriever=retriever,
        responder=responder,
    )

    app = FastAPI(title="memomind", version="0.1.0",
                  description="Agent 长期记忆系统：抽取->决策->存储->检索->遗忘")
    app.state.store = store
    app.state.chat = chat

    @app.get("/health")
    async def health() -> dict:
        # MM-7 修复：/health 曾与 /chat 共享同步路由线程池——慢 LLM 拖满 40 线程后
        # 探针一并饿死，被编排层杀进程等效整站不可用。改 async 直跑事件循环
        # （轻量内存计数），保证探针永远可达。
        return {
            "status": "ok",
            "memories": store.count(),
            "active": store.count(status=MemoryStatus.ACTIVE.value),
        }

    @app.post("/chat", response_model=ChatResponse)
    def post_chat(req: ChatRequest) -> ChatResponse:
        # MM-7 修复：并发闸——真模型 /chat 每请求占线程可达 90s，无上限会耗尽
        # 线程池。非阻塞获取失败即 503（背压而非排队饿死）。
        if not _CHAT_SEM.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="chat busy，稍后重试")
        try:
            result = chat.handle(req.session_id, req.message)
        finally:
            _CHAT_SEM.release()
        return ChatResponse(
            session_id=result.session_id,
            reply=result.reply,
            memories_used=[m.to_dict() for m in result.memories_used],
            facts_extracted=[
                {
                    "subject": f.subject, "predicate": f.predicate,
                    "object": f.object, "category": f.category,
                    "confidence": f.confidence, "polarity": f.polarity,
                }
                for f in result.facts_extracted
            ],
            ops=[op.to_dict() for op in result.ops],
        )

    @app.get("/memories")
    def get_memories(
        status: Optional[str] = Query(default=None),
        subject: Optional[str] = Query(default=None),
        q: Optional[str] = Query(default=None),
        limit: int = Query(default=100, le=1000),
    ) -> dict:
        if status is not None and status not in {s.value for s in MemoryStatus}:
            raise HTTPException(400, f"未知 status: {status}（可选 active/archived/superseded）")
        if q:
            records = store.search_text(q, status=status, limit=limit)
        else:
            records = store.list(status=status, subject=subject, limit=limit)
        return {"count": len(records), "memories": [r.to_dict() for r in records]}

    @app.post("/forget")
    def post_forget(req: ForgetRequest) -> dict:
        rec = store.get(req.memory_id)
        if rec is None:
            raise HTTPException(404, f"记忆不存在: {req.memory_id}")
        if rec.status != MemoryStatus.ACTIVE.value:
            raise HTTPException(409, f"记忆当前状态为 {rec.status}，仅 active 可手动遗忘")
        store.set_status(req.memory_id, MemoryStatus.ARCHIVED.value, time.time())
        return {"forgotten": req.memory_id, "status": MemoryStatus.ARCHIVED.value}

    @app.get("/graph/{entity}")
    def get_graph(entity: str, depth: int = Query(default=1, ge=1, le=3)) -> dict:
        sg = store.subgraph(entity, depth=depth)
        nodes = [
            {"id": n, "degree": sg.degree(n)}
            for n in sg.nodes
        ]
        edges = [
            {
                "source": u,
                "target": v,
                "predicate": data.get("predicate", ""),
                "memory_id": data.get("memory_id", ""),
                "category": data.get("category", ""),
                "confidence": data.get("confidence", 0.0),
            }
            for u, v, data in sg.edges(data=True)
        ]
        return {"entity": entity, "depth": depth, "nodes": nodes, "edges": edges}

    @app.post("/maintenance")
    def post_maintenance(req: MaintenanceRequest) -> dict:
        cfg = DecayConfig(half_life_days=req.half_life_days)
        report = run_decay(store, time.time(), cfg) if req.run_decay else None
        removed = compact(store, time.time(), cfg) if req.run_compact else 0
        return {
            "decay": report.to_dict() if report else None,
            "compacted": removed,
            "active": store.count(status=MemoryStatus.ACTIVE.value),
        }

    # 静态记忆浏览器
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    return app


def main() -> None:  # pragma: no cover - 手动启动入口
    import uvicorn

    uvicorn.run(
        "memomind.api:create_app",
        host="127.0.0.1",
        port=int(os.environ.get("MEMOMIND_PORT", "8770")),
        factory=True,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
