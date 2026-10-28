"""memomind 现场演示：3 个确定性会话，打印每一步的记忆变化轨迹。

    python scripts/demo.py

三个 demo 覆盖三条核心能力线：
  Demo 1 新增+跨会话保持：第一会话自我介绍 -> 第二会话提问，记忆被召回并注入应答；
  Demo 2 更新+强化：改投岗位 -> 旧记忆 superseded；重复提及技能 -> 置信度强化；
  Demo 3 冲突+遗忘：投递 -> 面试 -> 流程结束的状态链 + 时间衰减归档演示。

全程 RuleExtractor + RuleOpsDecider + MockResponder，无网络无随机，可重复跑。
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memomind.chat import MemoChat  # noqa: E402
from memomind.decay import DecayConfig, run_decay  # noqa: E402
from memomind.extract import RuleExtractor  # noqa: E402
from memomind.llm import MockResponder  # noqa: E402
from memomind.ops import RuleOpsDecider  # noqa: E402
from memomind.retrieve import RetrievalConfig, Retriever  # noqa: E402
from memomind.schema import MemoryRecord  # noqa: E402
from memomind.store import MemoryStore  # noqa: E402

DAY = 86400.0
T0 = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc).timestamp()


def fmt_record(r: MemoryRecord) -> str:
    mark = {"active": "✓", "superseded": "✗", "archived": "⌛"}[r.status]
    return (f"  {mark} [{r.status:>10}] {r.subject} {r.predicate} {r.object}"
            f"  (conf={r.confidence:.2f}, 来源={r.source_session or '-'})")


def show(title: str, store: MemoryStore) -> None:
    print(f"\n┌─ 记忆库状态 · {title}")
    for status in ("active", "superseded", "archived"):
        recs = store.list(status=status)
        if recs:
            for r in sorted(recs, key=lambda x: x.created_at):
                print(fmt_record(r))
    print("└─" + "─" * 60)


def run_turn(bot: MemoChat, session_id: str, text: str, now: float) -> None:
    print(f"\n▶ [{session_id}] 用户：{text}")
    result = bot.handle(session_id, text, now=now)
    hits = [f"{m.subject} {m.predicate} {m.object}" for m in result.memories_used]
    print(f"  检索命中: {hits if hits else '（无）'}")
    facts = [f"{f.subject} {f.predicate} {f.object}" for f in result.facts_extracted]
    print(f"  抽取事实: {facts if facts else '（无）'}")
    if result.ops:
        for op in result.ops:
            print(f"  决策: {op}")
    else:
        print("  决策: （无动作）")
    print(f"  助理：{result.reply}")


def demo1_new_and_recall() -> MemoryStore:
    print("=" * 70)
    print("Demo 1  新增与跨会话保持：会话 A 自我介绍，会话 B 提问仍记得")
    print("=" * 70)
    store = MemoryStore(":memory:", clock=lambda: T0)
    bot = MemoChat(store, RuleExtractor(), ops_decider=RuleOpsDecider(),
                   retriever=Retriever(store, RetrievalConfig()),
                   responder=MockResponder(), clock=lambda: T0)
    run_turn(bot, "sess_A1", "我叫李雷，我想投后端岗", T0)
    show("Demo1 · 会话 A 之后", store)
    run_turn(bot, "sess_B1", "我叫什么名字？我的目标岗位是什么？", T0 + 60)
    show("Demo1 · 会话 B 提问之后（注意检索命中的记忆来自会话 A）", store)
    return store


def demo2_update_and_reinforce() -> MemoryStore:
    print("\n" + "=" * 70)
    print("Demo 2  更新与强化：改投岗位（supersede）+ 重复提及技能（strengthen）")
    print("=" * 70)
    store = MemoryStore(":memory:", clock=lambda: T0)
    bot = MemoChat(store, RuleExtractor(), ops_decider=RuleOpsDecider(),
                   retriever=Retriever(store, RetrievalConfig()),
                   responder=MockResponder(), clock=lambda: T0)
    run_turn(bot, "sess_C1", "我想投后端岗", T0)
    run_turn(bot, "sess_C1", "我熟悉 Python", T0 + 30)
    show("Demo2 · 初始画像", store)
    run_turn(bot, "sess_C2", "改投 Agent 岗了", T0 + 86400)
    run_turn(bot, "sess_C2", "我掌握 Python", T0 + 86500)
    show("Demo2 · 更新后（后端岗被替代，Python 置信度 0.85 -> 0.93）", store)
    return store


def demo3_conflict_and_forget() -> MemoryStore:
    print("\n" + "=" * 70)
    print("Demo 3  冲突与遗忘：投递->面试->流程结束 状态链 + 衰减归档")
    print("=" * 70)
    store = MemoryStore(":memory:", clock=lambda: T0)
    clock = {"t": T0}

    def tick():
        return clock["t"]

    bot = MemoChat(store, RuleExtractor(), ops_decider=RuleOpsDecider(),
                   retriever=Retriever(store, RetrievalConfig(), clock=tick),
                   responder=MockResponder(), clock=tick)
    run_turn(bot, "sess_D1", "我投了字节跳动", tick())
    run_turn(bot, "sess_D2", "收到字节跳动的面试邀请", tick() + 3 * DAY)
    show("Demo3 · 面试中（:submitted 已被 :interviewing 替代）", store)
    run_turn(bot, "sess_D3", "字节挂了", tick() + 10 * DAY)
    show("Demo3 · 流程结束（:interviewing 被 :ended 替代）", store)
    clock["t"] += 130 * DAY
    report = run_decay(store, tick(), DecayConfig())
    print(f"\n▶ 时间推进 130 天并执行遗忘：过期归档 {report.expired_archived} 条，"
          f"衰减归档 {report.decay_archived} 条")
    show("Demo3 · 遗忘后（失效投递链全部归档，不再干扰检索）", store)
    run_turn(bot, "sess_D4", "我投过哪些公司？", tick())
    return store


if __name__ == "__main__":
    demo1_new_and_recall()
    demo2_update_and_reinforce()
    demo3_conflict_and_forget()
    print("\n演示结束。全部输出确定性可复现：RuleExtractor + RuleOpsDecider + MockResponder。")
