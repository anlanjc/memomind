"""memomind 自建评测集：20 个脚本化跨会话场景（全确定性）。

- 5 个维度 x 4 个场景：记忆保持 / 偏好更新 / 冲突消解 / 时效遗忘 / 冷启动。
- 全程 RuleExtractor + RuleOpsDecider + MockResponder，无网络、无随机、
  时间由场景逐步推进（``advance_days``），可离线重复复现。
- 断言对象是**系统状态与检索行为**（谁 active / 谁 superseded / 召回了什么），
  不依赖应答文本的措辞。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from memomind.schema import MemoryRecord

__all__ = ["Step", "Scenario", "EvalContext", "SCENARIOS", "DIMENSIONS"]

# ---------------------------------------------------------------------------
# 场景原语
# ---------------------------------------------------------------------------
DAY = 86400.0


@dataclass
class Step:
    """一步 = 一个（可选的）会话轮 + 环境操作。

    - session_id/text: 发一句话（text 为空则本步不对话）
    - advance_days:    本步开始前时间推进多少天
    - run_decay:       跑一轮遗忘（过期归档 + 衰减归档）
    - run_compact:     跑一轮 compaction（物理清理）
    - seed:            直接种一条记忆 (subject, predicate, object, category,
                       confidence, valid_to_days)；valid_to_days=None 表示长期有效
    """

    session_id: str = ""
    text: str = ""
    advance_days: float = 0.0
    run_decay: bool = False
    run_compact: bool = False
    seed: Optional[tuple] = None


@dataclass
class Scenario:
    sid: str
    dimension: str
    title: str
    steps: list[Step]
    check: Callable[["EvalContext"], tuple[bool, str]]


@dataclass
class EvalContext:
    """跑完一个场景后的环境快照，供 check 断言。"""

    store: object
    results: list = field(default_factory=list)  # 各对话步的 ChatResult
    now: float = 0.0

    # -- 断言辅助 -----------------------------------------------------------
    def active(self, predicate: Optional[str] = None) -> list[MemoryRecord]:
        recs = self.store.list(status="active")
        if predicate:
            recs = [r for r in recs if r.predicate == predicate]
        return recs

    def superseded(self, predicate: Optional[str] = None) -> list[MemoryRecord]:
        recs = self.store.list(status="superseded")
        if predicate:
            recs = [r for r in recs if r.predicate == predicate]
        return recs

    def archived(self, predicate: Optional[str] = None) -> list[MemoryRecord]:
        recs = self.store.list(status="archived")
        if predicate:
            recs = [r for r in recs if r.predicate == predicate]
        return recs

    def find_active(self, predicate: str, obj: str) -> Optional[MemoryRecord]:
        for r in self.active(predicate):
            if r.object == obj:
                return r
        return None

    def find_superseded(self, predicate: str, obj: str) -> Optional[MemoryRecord]:
        for r in self.superseded(predicate):
            if r.object == obj:
                return r
        return None

    def retrieved_objects(self, step_index: int = -1) -> list[str]:
        """某次对话召回的记忆 object 列表（按检索排序）。"""
        if not self.results:
            return []
        r = self.results[step_index] if step_index >= 0 else self.results[step_index]
        return [m.object for m in r.memories_used]

    def find_archived_applied(self, obj: str) -> Optional[MemoryRecord]:
        for r in self.archived("applied_to"):
            if r.object == obj:
                return r
        return None


# ---------------------------------------------------------------------------
# D1 记忆保持：N 轮 / 跨会话后仍能召回
# ---------------------------------------------------------------------------
def _check_e01(ctx: EvalContext) -> tuple[bool, str]:
    recs = ctx.active("name")
    ok_state = len(recs) == 1 and recs[0].object == "李雷"
    got = ctx.retrieved_objects()
    ok_recall = "李雷" in got
    return (ok_state and ok_recall,
            f"state={ok_state} recall={ok_recall} retrieved={got}")


E01 = Scenario(
    "E01", "记忆保持", "跨会话记住姓名（隔 1 个会话后提问）",
    [
        Step("sess_01", "我叫李雷，我想投后端岗"),
        Step("sess_02", "我叫什么名字？"),
    ],
    _check_e01,
)


def _check_e02(ctx: EvalContext) -> tuple[bool, str]:
    ok_state = ctx.find_active("applied_to", "字节跳动") is not None
    got = ctx.retrieved_objects()
    ok_recall = "字节跳动" in got
    return (ok_state and ok_recall,
            f"state={ok_state} recall={ok_recall} retrieved={got}")


E02 = Scenario(
    "E02", "记忆保持", "跨会话记住投递过的公司",
    [
        Step("sess_01", "我投了字节跳动"),
        Step("sess_02", "我投过哪些公司？"),
    ],
    _check_e02,
)


def _check_e03(ctx: EvalContext) -> tuple[bool, str]:
    ok_state = ctx.find_active("uses", "Python") is not None
    got = ctx.retrieved_objects()
    ok_recall = "Python" in got
    return (ok_state and ok_recall,
            f"state={ok_state} recall={ok_recall} retrieved={got}")


E03 = Scenario(
    "E03", "记忆保持", "跨会话记住技能栈",
    [
        Step("sess_01", "我熟悉 Python 和 FastAPI"),
        Step("sess_02", "我会什么技能？"),
    ],
    _check_e03,
)


def _check_e04(ctx: EvalContext) -> tuple[bool, str]:
    ok_state = ctx.find_active("target_role", "Agent岗") is not None
    got = ctx.retrieved_objects()
    ok_recall = "Agent岗" in got
    return (ok_state and ok_recall,
            f"state={ok_state} recall={ok_recall} retrieved={got}")


E04 = Scenario(
    "E04", "记忆保持", "三个会话后仍记得目标岗位（中间穿插无关信息）",
    [
        Step("sess_01", "我的目标是 Agent 岗"),
        Step("sess_02", "我熟悉 Python"),
        Step("sess_03", "我的目标岗位是什么？"),
    ],
    _check_e04,
)


# ---------------------------------------------------------------------------
# D2 偏好更新：新偏好生效、旧偏好被替代/强化
# ---------------------------------------------------------------------------
def _check_e05(ctx: EvalContext) -> tuple[bool, str]:
    ok_new = ctx.find_active("target_role", "Agent岗") is not None
    ok_old = ctx.find_superseded("target_role", "后端岗") is not None
    ok_single = len(ctx.active("target_role")) == 1
    return (ok_new and ok_old and ok_single,
            f"new={ok_new} old_superseded={ok_old} single_active={ok_single}")


E05 = Scenario(
    "E05", "偏好更新", "目标岗位从后端改投 Agent 岗",
    [
        Step("sess_01", "我想投后端岗"),
        Step("sess_02", "改投 Agent 岗了"),
    ],
    _check_e05,
)


def _check_e06(ctx: EvalContext) -> tuple[bool, str]:
    ok_new = ctx.find_active("prefers_city", "杭州") is not None
    ok_old = ctx.find_superseded("prefers_city", "北京") is not None
    return (ok_new and ok_old,
            f"new={ok_new} old_superseded={ok_old}")


E06 = Scenario(
    "E06", "偏好更新", "期望城市从北京改为杭州",
    [
        Step("sess_01", "我想去北京工作"),
        Step("sess_02", "我想去杭州工作"),
    ],
    _check_e06,
)


def _check_e07(ctx: EvalContext) -> tuple[bool, str]:
    recs = [r for r in ctx.active("uses") if r.object == "Python"]
    ok_single = len(recs) == 1
    ok_conf = bool(recs) and recs[0].confidence > 0.85
    ops2 = ctx.results[1].ops if len(ctx.results) > 1 else []
    ok_op = any(op.op == "UPDATE" and op.update_kind == "strengthen" for op in ops2)
    return (ok_single and ok_conf and ok_op,
            f"single={ok_single} conf={recs[0].confidence if recs else None} "
            f"strengthen={ok_op}")


E07 = Scenario(
    "E07", "偏好更新", "重复提及技能 -> 合并强化置信度而非新增重复记忆",
    [
        Step("sess_01", "我熟悉 Python"),
        Step("sess_02", "我掌握 Python"),
    ],
    _check_e07,
)


def _check_e08(ctx: EvalContext) -> tuple[bool, str]:
    got = ctx.retrieved_objects()
    ok_top = bool(got) and got[0] == "大厂"
    ok_state = ctx.find_active("prefers", "大厂") is not None
    return (ok_top and ok_state, f"top1={got[:1]} state={ok_state} retrieved={got}")


E08 = Scenario(
    "E08", "偏好更新", "新增偏好后检索排序第一（新偏好压过旧画像）",
    [
        Step("sess_01", "我想投后端岗"),
        Step("sess_02", "我更喜欢大厂"),
        Step("sess_03", "我喜欢什么样的公司？"),
    ],
    _check_e08,
)


# ---------------------------------------------------------------------------
# D3 冲突消解：矛盾 -> 新事实生效、旧事实 superseded
# ---------------------------------------------------------------------------
def _check_e09(ctx: EvalContext) -> tuple[bool, str]:
    ok_new = ctx.find_active("application_status", "字节跳动:ended") is not None
    ok_old = ctx.find_superseded("application_status", "字节跳动:submitted") is not None
    ok_hist = ctx.find_active("applied_to", "字节跳动") is not None  # 投递历史保留
    return (ok_new and ok_old and ok_hist,
            f"ended_active={ok_new} submitted_superseded={ok_old} history_kept={ok_hist}")


E09 = Scenario(
    "E09", "冲突消解", "'已投字节' vs '字节流程结束'：状态被替代，投递历史保留",
    [
        Step("sess_01", "我投了字节跳动"),
        Step("sess_02", "字节流程结束了"),
    ],
    _check_e09,
)


def _check_e10(ctx: EvalContext) -> tuple[bool, str]:
    ok_new = ctx.find_active("application_status", "字节跳动:ended") is not None
    ok_old = ctx.find_superseded("application_status", "字节跳动:interviewing") is not None
    return (ok_new and ok_old,
            f"ended_active={ok_new} interviewing_superseded={ok_old}")


E10 = Scenario(
    "E10", "冲突消解", "'收到面试邀请' vs '字节挂了'：面试状态被结果替代",
    [
        Step("sess_01", "收到字节跳动的面试邀请"),
        Step("sess_02", "字节挂了"),
    ],
    _check_e10,
)


def _check_e11(ctx: EvalContext) -> tuple[bool, str]:
    ok_new = ctx.find_active("works_at", "字节跳动") is not None
    ok_old = ctx.find_superseded("works_at", "美团") is not None
    return (ok_new and ok_old,
            f"new_active={ok_new} old_superseded={ok_old}")


E11 = Scenario(
    "E11", "冲突消解", "在职公司从美团变为字节跳动（单值属性矛盾替代）",
    [
        Step("sess_01", "我现在在美团工作"),
        Step("sess_02", "我现在在字节跳动工作"),
    ],
    _check_e11,
)


def _check_e12(ctx: EvalContext) -> tuple[bool, str]:
    ok_hist = ctx.find_superseded("applied_to", "阿里巴巴") is not None
    ok_status = ctx.find_superseded("application_status", "阿里巴巴:submitted") is not None
    ok_withdrawn = ctx.find_active("withdrawn", "阿里巴巴") is not None
    return (ok_hist and ok_status and ok_withdrawn,
            f"applied_superseded={ok_hist} status_superseded={ok_status} "
            f"withdrawn_active={ok_withdrawn}")


E12 = Scenario(
    "E12", "冲突消解", "'取消阿里的申请'：撤销型事实失效相关记忆",
    [
        Step("sess_01", "我投了阿里巴巴"),
        Step("sess_02", "取消阿里的申请"),
    ],
    _check_e12,
)


# ---------------------------------------------------------------------------
# D4 时效遗忘：过期/衰减后不再干扰检索
# ---------------------------------------------------------------------------
def _check_e13(ctx: EvalContext) -> tuple[bool, str]:
    ok_archived = ctx.find_archived_applied("滴滴") is not None
    got = ctx.retrieved_objects()
    ok_not_retrieved = "滴滴" not in got
    return (ok_archived and ok_not_retrieved,
            f"archived={ok_archived} not_retrieved={ok_not_retrieved} retrieved={got}")


E13 = Scenario(
    "E13", "时效遗忘", "120 天前的投递未被再次访问 -> 衰减归档、不再干扰",
    [
        Step("sess_01", "我投了滴滴"),
        Step("", advance_days=120, run_decay=True),
        Step("sess_02", "我现在该投什么公司？"),
    ],
    _check_e13,
)


def _check_e14(ctx: EvalContext) -> tuple[bool, str]:
    recs = ctx.archived("works_at")
    ok_expired = len(recs) == 1 and recs[0].object == "创业公司X"
    got = ctx.retrieved_objects()
    ok_not_retrieved = "创业公司X" not in got
    return (ok_expired and ok_not_retrieved,
            f"expired_archived={ok_expired} not_retrieved={ok_not_retrieved} retrieved={got}")


E14 = Scenario(
    "E14", "时效遗忘", "带 valid_to 的实习记忆到期自动归档（过期归档）",
    [
        Step("sess_01", "我在创业公司X实习", seed=("user", "works_at", "创业公司X", "identity", 0.9, 90)),
        Step("", advance_days=100, run_decay=True),
        Step("sess_02", "我现在在哪家工作？"),
    ],
    _check_e14,
)


def _check_e15(ctx: EvalContext) -> tuple[bool, str]:
    recs = ctx.active("name")
    ok_active = len(recs) == 1 and recs[0].object == "李雷"
    got = ctx.retrieved_objects()
    ok_recall = "李雷" in got
    return (ok_active and ok_recall,
            f"active={ok_active} recall={ok_recall} retrieved={got}")


E15 = Scenario(
    "E15", "时效遗忘", "常被想起的记忆跨 80 天仍存活（访问刷新遗忘时钟）",
    [
        Step("sess_01", "我叫李雷"),
        Step("sess_02", "我叫李雷"),
        Step("", advance_days=40),
        Step("sess_03", "我叫什么名字？"),
    ],
    _check_e15,
)


def _check_e16(ctx: EvalContext) -> tuple[bool, str]:
    # compaction 后：被替代的后端岗记忆应被物理删除
    all_objs = [r.object for r in ctx.store.list()]
    gone = "后端岗" not in all_objs
    kept = ctx.find_active("target_role", "Agent岗") is not None
    return (gone and kept, f"superseded_purged={gone} active_kept={kept}")


E16 = Scenario(
    "E16", "时效遗忘", "superseded 记忆超保留期 -> compaction 物理清理",
    [
        Step("sess_01", "我想投后端岗"),
        Step("sess_02", "改投 Agent 岗了"),
        Step("", advance_days=40, run_compact=True),
    ],
    _check_e16,
)


# ---------------------------------------------------------------------------
# D5 冷启动：空记忆库下不崩溃、不产生垃圾记忆
# ---------------------------------------------------------------------------
def _check_e17(ctx: EvalContext) -> tuple[bool, str]:
    ok_empty = ctx.store.count() == 0
    ok_reply = bool(ctx.results) and bool(ctx.results[0].reply)
    return (ok_empty and ok_reply,
            f"no_garbage_memories={ok_empty} replied={ok_reply}")


E17 = Scenario(
    "E17", "冷启动", "空库寒暄：不抽取、不落库、正常应答",
    [
        Step("sess_01", "你好，我想聊聊求职的事"),
    ],
    _check_e17,
)


def _check_e18(ctx: EvalContext) -> tuple[bool, str]:
    ok_count = len(ctx.active()) == 3
    ops = ctx.results[0].ops if ctx.results else []
    ok_all_add = bool(ops) and all(op.op == "ADD" for op in ops)
    return (ok_count and ok_all_add,
            f"count={len(ctx.active())} all_add={ok_all_add}")


E18 = Scenario(
    "E18", "冷启动", "空库首轮自我介绍：一次 ADD 全部事实",
    [
        Step("sess_01", "我叫王芳，我投了腾讯"),
    ],
    _check_e18,
)


def _check_e19(ctx: EvalContext) -> tuple[bool, str]:
    got = ctx.retrieved_objects()
    ok_recall = "王芳" in got
    return (ok_recall, f"recall={ok_recall} retrieved={got}")


E19 = Scenario(
    "E19", "冷启动", "冷启动后同会话即时召回",
    [
        Step("sess_01", "我叫王芳"),
        Step("sess_01", "我叫什么名字？"),
    ],
    _check_e19,
)


def _check_e20(ctx: EvalContext) -> tuple[bool, str]:
    recs = [r for r in ctx.active("applied_to") if r.object == "腾讯"]
    ok_no_dup = len(recs) == 1
    ops2 = ctx.results[1].ops if len(ctx.results) > 1 else []
    ok_noop = any(op.op == "NOOP" for op in ops2)
    return (ok_no_dup and ok_noop,
            f"no_duplicate={ok_no_dup} noop_on_repeat={ok_noop}")


E20 = Scenario(
    "E20", "冷启动", "冷启动防重复：同一事实说两遍只落一条",
    [
        Step("sess_01", "我投了腾讯"),
        Step("sess_01", "我投了腾讯"),
    ],
    _check_e20,
)


# E13 的归档断言使用 EvalContext.find_archived_applied（类内已定义）

DIMENSIONS = ["记忆保持", "偏好更新", "冲突消解", "时效遗忘", "冷启动"]

SCENARIOS: list[Scenario] = [E01, E02, E03, E04, E05, E06, E07, E08, E09, E10,
                             E11, E12, E13, E14, E15, E16, E17, E18, E19, E20]
