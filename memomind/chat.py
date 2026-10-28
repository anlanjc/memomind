"""求职记忆助理主循环：retrieve -> 注入 -> 应答 -> extract -> ops -> store。

一条消息的处理管线（全链路，每步产物都记录在 :class:`ChatResult` 里）：

    1. retrieve   混合检索相关长期记忆（刷新被命中记忆的 last_accessed）
    2. render     渲染带来源/时效标注的记忆注入块
    3. respond    LLM/Mock 基于记忆块应答（MockResponder 确定性）
    4. extract    从本轮话里抽候选事实
    5. decide     ops 决策器对照 active 记忆做 ADD/UPDATE/DELETE/NOOP
    6. apply      落库（含 supersede/强化），记录 source_session

跨会话：session_id 只影响 source_session 溯源与演示，长期记忆本身
跨会话共享 —— 换 session 重开一问，旧记忆仍可被检索（这是与"聊天
历史窗口"的本质区别，也是面试叙事的核心）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .extract import BaseExtractor
from .llm import MockResponder, OpenAICompatibleClient
from .ops import RuleOpsDecider
from .retrieve import Retriever, ScoredMemory
from .schema import ExtractedFact, MemoryOp, MemoryRecord
from .store import MemoryStore

__all__ = ["ChatResult", "MemoChat", "OpenAIResponder"]


@dataclass
class ChatResult:
    session_id: str
    user_text: str
    reply: str
    memories_used: list[MemoryRecord] = field(default_factory=list)
    facts_extracted: list[ExtractedFact] = field(default_factory=list)
    ops: list[MemoryOp] = field(default_factory=list)
    ops_log: list[dict] = field(default_factory=list)

    def ops_summary(self) -> str:
        if not self.ops:
            return "无"
        return ", ".join(f"{op.op}" for op in self.ops)


class OpenAIResponder:
    """真模型应答器：把记忆块注入 system prompt（接真模型时替换 MockResponder）。"""

    SYSTEM_TEMPLATE = """你是一个求职记忆助理。下面是与本轮对话相关的长期记忆（可能为空），
回答时优先利用记忆，并在引用时说明"根据我的记忆"。记忆块：

{memory_block}
"""

    def __init__(self, client: OpenAICompatibleClient) -> None:
        self.client = client

    def respond(self, session_id: str, user_text: str, memory_block: str) -> str:
        system = self.SYSTEM_TEMPLATE.format(memory_block=memory_block or "（空）")
        return self.client.chat(system, user_text)


class MemoChat:
    """把五层串起来的主循环。全部依赖可注入，测试/评测全确定性。"""

    def __init__(
        self,
        store: MemoryStore,
        extractor: BaseExtractor,
        ops_decider=None,
        retriever: Optional[Retriever] = None,
        responder=None,
        clock=None,
    ) -> None:
        self.store = store
        self.extractor = extractor
        self.ops_decider = ops_decider or RuleOpsDecider()
        self.retriever = retriever or Retriever(store, clock=clock)
        self.responder = responder or MockResponder()
        self.clock = clock or time.time

    def handle(self, session_id: str, text: str, now: Optional[float] = None) -> ChatResult:
        now = self.clock() if now is None else now

        # 1+2) 检索并渲染注入块
        scored = self.retriever.retrieve(text, now)
        memory_block = self.retriever.render_block(scored, now)
        memories_used = [e.record for e in scored]

        # 3) 应答
        reply = self.responder.respond(session_id, text, memory_block)

        # 4) 抽取
        facts = self.extractor.extract(text, session_id, now)

        # 5) 决策（对照当前 active 快照）
        existing = self.store.list_active(now)
        ops = self.ops_decider.decide(facts, existing, now)

        # 6) 落库
        ops_log = self.store.apply_ops(ops, source_session=session_id, now=now)

        return ChatResult(
            session_id=session_id,
            user_text=text,
            reply=reply,
            memories_used=memories_used,
            facts_extracted=facts,
            ops=ops,
            ops_log=ops_log,
        )
