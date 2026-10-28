"""事实抽取层：从一轮对话里抽 (subject, predicate, object, category, confidence) 候选事实。

两个 provider，同一接口 :class:`BaseExtractor.extract`：

- ``RuleExtractor``：正则规则 + 实体别名归一化，**确定性**、零网络，
  测试 / 评测 / 离线演示全部用它。领域限定"求职"，规则表覆盖：
  投递、流程状态、目标岗位、偏好、技能、在职、城市、撤销。
- ``OpenAICompatibleExtractor``：httpx 调 OpenAI 兼容接口（默认 DashScope
  兼容模式），要求模型返回严格 JSON；输出再经 :mod:`memomind.normalize`
  谓词映射层归一成规范谓词（LLM 抽取"语义对、命名歪"的系统化修复，见该
  模块 docstring 与 evals/eval_set100_report.md）；用于接真模型，评测口径
  不变（把 RuleExtractor 换成本类，重跑同一条命令即可复现 README 流程）。
- ``HybridExtractor``：组合前两者的混合抽取器——LLM 为主、LLM 抽空时
  回退规则底线（真模型空抽召回波动的架构级修复），开关默认开、事件留痕。

抽取只负责"说出事实"，**不判断**新旧与矛盾 —— 那是 ops 决策层的职责。
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from .llm import OpenAICompatibleClient
from .normalize import (  # noqa: F401  再导出：别名表是两套抽取器的共享基础设施
    COMPANY_ALIASES,
    ROLE_VOCAB,
    _norm_company,
    is_company_like,
    normalize_facts,
)
from .schema import ExtractedFact

logger = logging.getLogger(__name__)

__all__ = [
    "BaseExtractor",
    "RuleExtractor",
    "OpenAICompatibleExtractor",
    "HybridExtractor",
    "COMPANY_ALIASES",
    "is_question",
]

_QUESTION_MARKERS = re.compile(r"[?？]\s*$|什么|哪些|哪个|怎么|如何|多少|吗\s*[?？]?\s*$")


def is_question(turn: str) -> bool:
    """RuleExtractor 的守门员：疑问句不抽事实（"我叫什么名字？"不是自我介绍）。"""
    return bool(_QUESTION_MARKERS.search(turn.strip()))


def _norm_role(role: str) -> str:
    return re.sub(r"\s+", "", role.strip())


class BaseExtractor(ABC):
    """抽取器接口。``now`` 由调用方注入以保持确定性。"""

    @abstractmethod
    def extract(
        self, turn: str, session_id: str = "", now: Optional[float] = None
    ) -> list[ExtractedFact]:
        ...


# ---------------------------------------------------------------------------
# 规则抽取器
# ---------------------------------------------------------------------------
# 规则表：每条规则 = (规则名, 正则, 构建函数)。
# 构建函数 (match, session_id) -> list[ExtractedFact]，同一轮可产多条事实
# （例如"我投了字节跳动"会同时产出 applied_to 与 application_status 两条）。
# 公司名字符类（不带量词；各规则按需追加 {2,10} / 非贪婪量词）
_COMPANY = r"[\u4e00-\u9fa5A-Za-z0-9·&]"


def _f_name(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    return [ExtractedFact("user", "name", m.group("name"), "identity", 0.99,
                          mentioned_text=m.group(0), rule="name")]


def _f_applied(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    facts = []
    for part in re.split(r"[和与、,，]", m.group("company")):  # "美团和快手" -> 两家公司
        comp = _norm_company(part)
        if not is_company_like(comp):
            continue
        facts.append(
            ExtractedFact("user", "applied_to", comp, "application", 0.90,
                          mentioned_text=m.group(0), rule="applied"))
        facts.append(
            ExtractedFact("user", "application_status", f"{comp}:submitted", "application", 0.90,
                          mentioned_text=m.group(0), rule="applied"))
    return facts


def _f_interview(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    comp = _norm_company(m.group("company"))
    if not is_company_like(comp):
        return []
    return [ExtractedFact("user", "application_status", f"{comp}:interviewing", "application", 0.95,
                          mentioned_text=m.group(0), rule="interview")]


def _f_offer(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    comp = _norm_company(m.group("company"))
    if not is_company_like(comp):
        return []
    return [ExtractedFact("user", "application_status", f"{comp}:offer", "application", 0.98,
                          mentioned_text=m.group(0), rule="offer")]


def _f_status_end(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    comp = _norm_company(m.group("company") or m.group("company2"))
    if not is_company_like(comp):
        return []
    return [ExtractedFact("user", "application_status", f"{comp}:ended", "application", 0.95,
                          mentioned_text=m.group(0), rule="status_end")]


def _f_withdrawn(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    comp = _norm_company(m.group("company"))
    return [ExtractedFact("user", "withdrawn", comp, "application", 0.95,
                          polarity="negative", mentioned_text=m.group(0), rule="withdrawn")]


def _f_target_role(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    return [ExtractedFact("user", "target_role", _norm_role(m.group("role")), "preference", 0.90,
                          mentioned_text=m.group(0), rule="target_role")]


def _f_prefers(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    return [ExtractedFact("user", "prefers", m.group("obj"), "preference", 0.75,
                          mentioned_text=m.group(0), rule="prefers")]


def _f_city(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    return [ExtractedFact("user", "prefers_city", m.group("city"), "preference", 0.80,
                          mentioned_text=m.group(0), rule="city")]


def _f_works_at(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    comp = _norm_company(m.group("company"))
    if not is_company_like(comp):
        return []
    return [ExtractedFact("user", "works_at", comp, "identity", 0.90,
                          mentioned_text=m.group(0), rule="works_at")]


# 不同熟练度动词 -> 不同置信度（重复提及可走强化分支）
SKILL_CONF: dict[str, float] = {"掌握": 0.88, "熟悉": 0.85, "会用": 0.82, "用过": 0.80, "使用": 0.80}

# 技能切分时丢弃的代词/口语句
_SKILL_STOP = {"我", "你", "他", "她", "喜欢", "更喜欢", "比较", "非常"}


def _f_skills(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    raw = m.group("skills")
    parts = [p.strip() for p in re.split(r"[、,，/]|和|与", raw) if p.strip()]
    head = m.group(0)
    conf = 0.85
    for kw, c in SKILL_CONF.items():
        if kw in head:
            conf = c
            break
    facts = []
    for p in parts:
        p = re.sub(r"\s+", "", p)
        if 1 <= len(p) <= 24 and p not in _SKILL_STOP:
            facts.append(ExtractedFact("user", "uses", p, "skill", conf,
                                       mentioned_text=m.group(0), rule="skills"))
    return facts


def _f_withdrawn_with_alt(m: "re.Match[str]", session_id: str) -> list[ExtractedFact]:
    comp_raw = m.group("company") or m.group("company2")
    comp = _norm_company(comp_raw)
    if not is_company_like(comp):
        return []
    return [ExtractedFact("user", "withdrawn", comp, "application", 0.95,
                          polarity="negative", mentioned_text=m.group(0), rule="withdrawn")]


RULES: list[tuple[str, "re.Pattern[str]", Callable]] = [
    # 名字："我叫李雷"
    ("name", re.compile(r"我叫\s*(?P<name>[\u4e00-\u9fa5A-Za-z·]{2,8})"), _f_name),
    # 撤销（先于 applied，避免"不想投阿里了"先命中别的规则）
    ("withdrawn", re.compile(
        r"(?:取消|撤回|放弃)(?:了)?\s*(?P<company>" + _COMPANY + r"{2,10}?)"
        r"(?:的)?(?:申请|投递|流程|岗位)?(?=[，。,.\s;；!！?？]|$)"
        r"|(?:不想投|不再投|不再考虑|不考虑)了?\s*(?P<company2>" + _COMPANY + r"{2,10}?)"
        r"(?:了|啦)?(?=[，。,.\s;；!！?？]|$)"
    ), _f_withdrawn_with_alt),
    # 收到 offer："收到字节的offer"
    ("offer", re.compile(
        r"收到\s*(?P<company>" + _COMPANY + r"{2,10}?)\s*的?\s*[Oo]ffer"), _f_offer),
    # 面试邀请："收到字节的面试邀请"
    ("interview", re.compile(
        r"收到\s*(?P<company>" + _COMPANY + r"{2,10}?)\s*的?\s*面试(?:邀请|通知)"), _f_interview),
    # 流程结束/挂了："字节流程结束了" / "字节挂了"
    ("status_end", re.compile(
        r"(?P<company>" + _COMPANY + r"{2,10}?)\s*的?\s*(?:流程|面试|申请|简历)\s*"
        r"(?:已经|刚)?(?:挂了|被拒了|被拒|拒了|没通过|未通过|结束了|终止了|终止)"
        r"|(?P<company2>" + _COMPANY + r"{2,10}?)\s*的?\s*(?:已经|刚)?"
        r"(?:挂了|被拒了|被拒|拒了|没通过|未通过|终止)"), _f_status_end),
    # 投递："我投了字节跳动" / "我已经投了字节的Agent岗"
    # 负向后视挡掉"不想投/不再投/改投/想投"等非投递陈述
    ("applied", re.compile(
        r"(?<![不想再无改])投(?:递|了|递了|出了)?了?\s*(?P<company>" + _COMPANY + r"{2,10})"
        r"(?:的\s*[\u4e00-\u9fa5A-Za-z\s]{0,12}?(?:岗|岗位|工程师|开发)?)?"
        r"(?:的?简历)?(?:了)?"), _f_applied),
    # 目标岗位："我想投后端岗" / "改投 Agent 岗了"
    ("target_role", re.compile(
        r"(?:想投|打算投|主要投|目标是|目标岗位是|想改投|改投|转向)\s*"
        r"(?P<role>(?:大模型|Agent|后端|前端|算法|产品|数据|测试|运维|全栈|客户端|基础设施)\s*"
        r"(?:工程师|开发|岗|岗位)?)"), _f_target_role),
    # 偏好："我更喜欢远程办公"
    ("prefers", re.compile(
        r"(?:更喜欢|偏好|比较喜欢|喜欢|倾向)(?:于)?\s*"
        r"(?P<obj>[^，。,.;；!！?？\s]{2,12})"), _f_prefers),
    # 期望城市："我想去杭州工作"
    ("city", re.compile(
        r"(?:想去|希望去|打算去|想搬到|搬到)\s*(?P<city>[\u4e00-\u9fa5]{2,4}?)\s*(?:工作|发展|生活)?"),
     _f_city),
    # 在职："我现在在美团工作"
    ("works_at", re.compile(
        r"(?:现在)?在\s*(?P<company>" + _COMPANY + r"{2,10})\s*(?:工作|上班|任职)"), _f_works_at),
    # 技能："我熟悉 Python 和 FastAPI"
    ("skills", re.compile(
        r"(?:熟悉|掌握|会用|用过|使用)\s*(?P<skills>[A-Za-z0-9._+#\u4e00-\u9fa5和、/\s\-]{1,60}?)"
        r"(?=[。；;!！?？，,]|$)"), _f_skills),
]


class RuleExtractor(BaseExtractor):
    """确定性规则抽取器（求职域）。不联网、不随机、可全量单测。"""

    name = "rule"

    def extract(
        self, turn: str, session_id: str = "", now: Optional[float] = None
    ) -> list[ExtractedFact]:
        turn = turn.strip()
        if not turn or is_question(turn):
            return []
        facts: list[ExtractedFact] = []
        seen_triples: set[tuple[str, str, str]] = set()
        for _rule_name, pattern, builder in RULES:
            m = pattern.search(turn)
            if not m:
                continue
            for f in builder(m, session_id):
                if f.triple_key not in seen_triples:
                    seen_triples.add(f.triple_key)
                    facts.append(f)
        return facts


# ---------------------------------------------------------------------------
# OpenAI 兼容抽取器（接真模型）
# ---------------------------------------------------------------------------
_EXTRACT_SYSTEM_PROMPT = """你是求职助理的记忆抽取器。从用户这轮话里抽取可长期记忆的事实，
只抽"主谓宾"可形式化的事实，输出严格 JSON（不要 markdown 代码块）：
{"facts":[{"subject":"user","predicate":"applied_to","object":"字节跳动",
"category":"application|preference|identity|skill|event|other",
"confidence":0.0-1.0,"polarity":"positive|negative"}]}
规则：
- subject 一律用 "user"（用户本人的事实）；公司名用全称（如 字节跳动/阿里巴巴）。
- polarity=negative 表示撤销/否定（如"不想投了""取消申请"）。
- 疑问句、寒暄、无法形式化的内容返回 {"facts":[]}。"""


class OpenAICompatibleExtractor(BaseExtractor):
    """调用 OpenAI 兼容 /chat/completions 抽取事实（DashScope 兼容模式可用）。

    缺 API key 时抛 :class:`~memomind.llm.MissingLLMConfigError`。
    输出经 :func:`~memomind.normalize.normalize_facts` 归一成规范谓词；
    原始（未归一）事实保留在 ``last_raw_facts`` 供评测对比与审计。
    """

    name = "openai_compatible"

    def __init__(
        self,
        client: Optional[OpenAICompatibleClient] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
    ) -> None:
        self.client = client or OpenAICompatibleClient(
            base_url=base_url, api_key=api_key, model=model
        )
        self.temperature = temperature
        self.last_raw_facts: list[ExtractedFact] = []

    def extract(
        self, turn: str, session_id: str = "", now: Optional[float] = None
    ) -> list[ExtractedFact]:
        if not turn.strip():
            return []
        raw = self.client.chat(_EXTRACT_SYSTEM_PROMPT, turn, temperature=self.temperature)
        facts = self._parse(raw)
        self.last_raw_facts = facts
        return normalize_facts(facts)

    @staticmethod
    def _parse(raw: str) -> list[ExtractedFact]:
        """容错解析：剥掉 markdown 代码围栏后 json.loads；失败返回空列表。"""
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM 抽取结果不是合法 JSON，已丢弃：%s", raw[:120])
            return []
        items = data.get("facts", []) if isinstance(data, dict) else []
        facts: list[ExtractedFact] = []
        for it in items:
            try:
                facts.append(
                    ExtractedFact(
                        subject=str(it.get("subject", "user")) or "user",
                        predicate=str(it["predicate"]),
                        object=str(it["object"]),
                        category=str(it.get("category", "other")),
                        confidence=float(it.get("confidence", 0.8)),
                        polarity=str(it.get("polarity", "positive")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("跳过无法解析的事实项：%s", it)
        return facts


class HybridExtractor(BaseExtractor):
    """混合抽取器：LLM 为主、规则底线兜底（LLM 空抽召回波动的架构级修复）。

    背景：真模型复测定稿残差 1 条是 LLM 抽取召回波动——temperature=0 下
    同一输入也可能返回空（evals/eval_set100_real_compare_v3.md：W09"滴滴挂了"
    三轮两次全匹配、一次空抽）。LLM 抽空时回退 :class:`RuleExtractor`：
    规则底线保证"说过的求职事实不因 LLM 抽空而丢"。这正是混合架构
    （规则打底 + LLM 增强）的职责边界——兜底做在抽取器组合层，
    归一化层（normalize.py）不偷跑规则抽取，两路对比口径保持可归因。

    - 开关默认开（``enabled=True``）；关闭时行为与 primary 完全一致。
    - 每次走到兜底路径都留事件（``events`` 列表 + 日志），``rescued`` 标记
      规则是否实际救回——LLM 抽空但规则也无事实（疑问句/寒暄）不算事故，
      但同样留痕，方便统计空抽率与救回率。
    - 兜底只在"结果为空"时触发：LLM 非空但抽得比规则少不合并——部分召回
      混流会让两路对比口径失去归因（规则事实混进 LLM 结果），不在本层做。
    """

    name = "hybrid"

    def __init__(
        self,
        primary: BaseExtractor,
        fallback: Optional[RuleExtractor] = None,
        enabled: bool = True,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or RuleExtractor()
        self.enabled = enabled
        self.events: list[dict] = []

    def extract(
        self, turn: str, session_id: str = "", now: Optional[float] = None
    ) -> list[ExtractedFact]:
        facts = self.primary.extract(turn, session_id, now)
        if facts or not self.enabled:
            return facts
        rescued = self.fallback.extract(turn, session_id, now)
        self.events.append(
            {
                "session_id": session_id,
                "turn": turn,
                "llm_facts": 0,
                "fallback_used": True,
                "rescued": bool(rescued),
                "facts": [list(f.triple_key) for f in rescued],
            }
        )
        if rescued:
            logger.warning(
                "LLM 抽取为空，规则兜底救回 %d 条事实：%s",
                len(rescued),
                [f.triple_key for f in rescued],
            )
        else:
            logger.info("LLM 抽取为空，规则兜底也无事实（疑问句/寒暄/口语句）")
        return rescued
