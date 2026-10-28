"""chat.py：全链路主循环（检索->注入->应答->抽取->决策->落库）与跨会话。"""

from __future__ import annotations

from memomind.chat import MemoChat
from memomind.llm import MockResponder


def make_bot(store, clock):
    from memomind.extract import RuleExtractor
    from memomind.ops import RuleOpsDecider
    from memomind.retrieve import RetrievalConfig, Retriever

    return MemoChat(
        store,
        RuleExtractor(),
        ops_decider=RuleOpsDecider(),
        retriever=Retriever(store, RetrievalConfig(), clock=clock),
        responder=MockResponder(),
        clock=clock,
    )


def test_full_pipeline_adds_memories(store, clock):
    bot = make_bot(store, clock)
    result = bot.handle("s1", "我叫李雷，我投了字节跳动")
    assert result.reply  # MockResponder 有应答
    assert len(result.ops) == 3
    assert all(op.op == "ADD" for op in result.ops)
    assert store.count(status="active") == 3
    assert {r.source_session for r in store.list(status="active")} == {"s1"}


def test_cross_session_recall(store, clock):
    bot = make_bot(store, clock)
    bot.handle("s1", "我叫李雷")
    r2 = bot.handle("s2", "我叫什么名字？")  # 换会话
    assert [m.object for m in r2.memories_used] == ["李雷"]
    # 召回刷新了 last_accessed
    rec = [r for r in store.list(status="active") if r.predicate == "name"][0]
    assert rec.last_accessed == clock.t


def test_cross_session_update_supersedes(store, clock):
    bot = make_bot(store, clock)
    bot.handle("s1", "我想投后端岗")
    r2 = bot.handle("s2", "改投 Agent 岗了")
    assert any(op.op == "UPDATE" and op.update_kind == "supersede" for op in r2.ops)
    statuses = {(r.object, r.status) for r in store.list()}
    assert ("后端岗", "superseded") in statuses
    assert ("Agent岗", "active") in statuses


def test_duplicate_turn_is_noop(store, clock):
    bot = make_bot(store, clock)
    bot.handle("s1", "我投了腾讯")
    r2 = bot.handle("s1", "我投了腾讯")
    assert all(op.op == "NOOP" for op in r2.ops)
    assert store.count(status="active") == 2  # 不产生重复记忆


def test_memory_block_injected_into_reply(store, clock):
    bot = make_bot(store, clock)
    bot.handle("s1", "我叫李雷")
    r2 = bot.handle("s2", "我叫什么名字？")
    assert "李雷" in r2.reply  # MockResponder 复述了注入块内容


def test_empty_turn_and_garbage_are_safe(store, clock):
    bot = make_bot(store, clock)
    r1 = bot.handle("s1", "你好")
    assert r1.ops == [] or all(op.op == "NOOP" for op in r1.ops)
    r2 = bot.handle("s1", "！@#￥%……")
    assert store.count() == 0
