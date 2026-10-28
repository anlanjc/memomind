"""谓词映射层：LLM 抽出的自由谓词/实体 -> 规范谓词词典的确定性归一化。

背景（evals/eval_set100_report.md 真模型对比 0/20 的系统性归因）：LLM 抽取
"语义对、命名歪"——谓词用自然语言变体（has_skill / wants_to_apply_to /
received_offer_from ...），投递不产隐含状态伴随对，撤销事实谓词错挂成
applied_to，公司名归一体系与规则版分叉（滴滴出行 vs 滴滴）。后果是 LLM
输出直接进 ops 决策矩阵会失效：conflict_key 靠规范谓词分域，未注册谓词
一律降级 per_object，单值属性（name/target_role/...）的矛盾消解与状态机
查询（application_status）同时失灵。

本模块是 OpenAICompatibleExtractor 的后处理层，全部确定性、可离线单测：

1. 状态改写   STATUS_ALIASES：状态类自由谓词 -> application_status:{实体}:{状态}
2. 谓词映射   PREDICATE_ALIASES：自由谓词 -> 规范谓词（ROLE_ONLY_SOURCES 条目
              仅当宾语是岗位才映射，公司宾语的"想投"不是目标岗位，保留原样）
2.5 亚词兜底  词典未命中的谓词按语义词根前缀归一（LLM 会造词典没登记的
              同义变体，v3 复测实测）；不命中原样保留
3. 宾语感知   applied_to/prefers + 岗位宾语 -> target_role（"改投后端岗"不是投
              公司；prefers+岗位=目标岗位偏好，v4 U01 实测补）
4. 极性修正   negative + 投递/状态谓词 -> withdrawn:{实体}（撤销留档语义；
              ops 层本就凭 polarity 走撤销路径，规范化后审计谓词不再错挂）
5. 实体归一   公司域谓词过 COMPANY_ALIASES（与 RuleExtractor 共享同一张表，
              别名表作为两套抽取器的共享基础设施）
6. 宾语规范   target_role 宾语 _fold_role：去空白 + 吸收"开发/工程师"嵌入缀 +
              "岗位"后缀折迭为"岗"（LLM 会展开缩写："后端岗"->"后端岗位" v3
              实测、"后端开发岗位" v4 实测）
7. 伴随补全   positive applied_to:X 且批内无任何 X 的状态 -> 补
              application_status:X:submitted（规则版 _f_applied 的伴随对不变量）
8. 类别归一   规范谓词 -> 规范 category

设计红线：映射失败不猜测——未登记谓词原样保留，走 ops 的 per_object 兜底
（宁可并存不可误杀）；本层只做"能确定"的改写，不确定的语义交给决策层。
"""

from __future__ import annotations

import re
from typing import Optional

from .schema import ExtractedFact

__all__ = [
    "COMPANY_ALIASES",
    "ROLE_VOCAB",
    "is_company_like",
    "is_role_like",
    "normalize_fact",
    "normalize_facts",
    "PREDICATE_ALIASES",
    "STATUS_ALIASES",
]

# ---------------------------------------------------------------------------
# 实体归一化：口语短称/LLM 全称 -> 规范实体名。冲突消解依赖规范名，否则
# "字节"和"字节跳动"、"滴滴"和"滴滴出行"会被当成两家公司，矛盾检测失效。
# 本表是 RuleExtractor 与 LLM 归一化层共享的基础设施。
# ---------------------------------------------------------------------------
COMPANY_ALIASES: dict[str, str] = {
    "字节": "字节跳动",
    "阿里": "阿里巴巴",
    "蚂蚁": "蚂蚁集团",
    "腾讯": "腾讯",
    "美团": "美团",
    "快手": "快手",
    "百度": "百度",
    "京东": "京东",
    "小红书": "小红书",
    "拼多多": "拼多多",
    "滴滴": "滴滴",
    "滴滴出行": "滴滴",  # LLM 倾向输出全称（W09 实测证据），规范名与规则版对齐
    "深度求索": "DeepSeek",  # LLM 会把英文名翻译成官方中文名（v4 A05 实测证据）
    "网易": "网易",
    "华为": "华为",
    "米哈游": "米哈游",
    "deepseek": "DeepSeek",
}

# 岗位词表：投递规则的宾语若是岗位词而非公司名，判定为无效抽取
ROLE_VOCAB = {
    "Agent", "大模型", "后端", "前端", "算法", "产品", "数据", "测试",
    "运维", "全栈", "客户端", "基础设施", "工程师", "开发",
}


def is_company_like(name: str) -> bool:
    """归一化后是公司名（非岗位词、非空）才允许产出投递类事实。"""
    if not name or name in ROLE_VOCAB:
        return False
    return True


def _norm_company(name: str) -> str:
    """公司名归一化：剥掉粘连的岗位/申请后缀与"的"，再做别名映射。"""
    name = re.sub(r"(?:\s*(?:Agent|大模型|后端|前端|算法|产品|数据|测试|运维|全栈|客户端|基础设施)"
                  r"(?:工程师|开发|岗位|岗))+$", "", name.strip())
    name = re.sub(r"(?:的?\s*(?:申请|投递|流程|岗位|简历|[Oo]ffer))+$", "", name)
    name = name.rstrip("的").strip()
    return COMPANY_ALIASES.get(name, COMPANY_ALIASES.get(name.lower(), name))


def is_role_like(obj: str) -> bool:
    """宾语本身是岗位（直接命中岗位词表，或剥掉岗位后缀后为空）。"""
    o = obj.strip()
    if not o:
        return False
    return o in ROLE_VOCAB or _norm_company(o) == ""


def _fold_role(obj: str) -> str:
    """岗位宾语折迭：去空白 + 吸收"开发/工程师"嵌入缀 + "岗位"后缀折迭为"岗"。

    v3 实测："后端岗"被 LLM 展开为"后端岗位"；v4 实测再变体"后端开发岗位"
    （多一个"开发"嵌入缀，让后缀折迭与 role 判定双双失效）。折迭后
    is_role_like 才能识别复合写法；空结果（宾语本身只有"开发/工程师"）不折。
    """
    obj = re.sub(r"\s+", "", obj)
    stripped = re.sub(r"(?:工程师|开发)(?=岗(?:位)?$)", "", obj)
    obj = stripped or obj
    return re.sub(r"岗位$", "岗", obj)


# ---------------------------------------------------------------------------
# 谓词词典：规范谓词是 ops 决策矩阵 / 检索意图映射的唯一口径。
# 词典条目全部来自真模型对比的实测证据（v1 real_model_report.md +
# v2 eval_set100_real_compare.md），而非凭空枚举。
# ---------------------------------------------------------------------------
# 状态类自由谓词 -> 规范状态值（object 改写为 {实体}:{状态}）
STATUS_ALIASES: dict[str, str] = {
    "received_offer_from": "offer",     # W05 实测
    "got_offer_from": "offer",
    "has_offer_from": "offer",
    "was_rejected_by": "ended",         # W09 实测
    "rejected_by": "ended",
    "got_rejected_by": "ended",
    "failed_interview_at": "ended",     # v1 实测（"没过一面"）
    "failed_at": "ended",
    "has_interview_with": "interviewing",
    "interviewing_at": "interviewing",
    "interview_invitation_from": "interviewing",
}

# 自由谓词 -> 规范谓词
PREDICATE_ALIASES: dict[str, str] = {
    # 身份
    "has_name": "name",                 # M10 / v1 实测
    "full_name": "name",
    "is_named": "name",
    # 技能
    "has_skill": "uses",                # U08 / M02 / v1 实测
    "skilled_in": "uses",
    "proficient_in": "uses",
    "knows": "uses",
    "familiar_with": "uses",
    # 城市偏好
    "wants_to_work_in": "prefers_city",  # U17 实测
    "prefers_location": "prefers_city",  # v1 实测（"最好杭州或者上海"）
    "preferred_city": "prefers_city",
    "preferred_location": "prefers_city",
    # 目标岗位（岗位条件映射，见 ROLE_ONLY_SOURCES）
    "wants_to_apply_to": "target_role",  # U01 实测
    "interested_in": "target_role",      # U16 / v1 实测
    "intends_to_apply_for": "target_role",
    "desired_role": "target_role",
    "target_position": "target_role",
    # 投递变体
    "applied_for": "applied_to",
    "has_applied_to": "applied_to",
    # 在职变体
    "employed_at": "works_at",
    "is_working_at": "works_at",
    "current_employer": "works_at",
}
# 仅当宾语是岗位才映射的条目（PREDICATE_ALIASES 的子集）：
# 公司宾语的"想投/感兴趣"不是目标岗位——保留原谓词走 per_object 兜底，
# 绝不改写成 applied_to（"想投"不等于"已投"）。
ROLE_ONLY_SOURCES = {
    "wants_to_apply_to",                # U01 实测
    "interested_in",                    # U16 / v1 实测
    "intends_to_apply_for",
    "desired_role",
    "target_position",
}

# 规范谓词 -> 规范 category（抽取器给出的 category 仅为参考）
PREDICATE_CATEGORY: dict[str, str] = {
    "name": "identity",
    "works_at": "identity",
    "applied_to": "application",
    "application_status": "application",
    "withdrawn": "application",
    "target_role": "preference",
    "prefers": "preference",
    "prefers_city": "preference",
    "uses": "skill",
}
_CANONICAL = frozenset(PREDICATE_CATEGORY)

# 亚词兜底（词典未命中时触发）：LLM 会造词典没登记的谓词变体——v3 复测
# 实测 wants_to_apply / prefers_work_location / is_familiar_with，与 v2 的
# wants_to_apply_to / wants_to_work_in / has_skill 同语义不同拼法。按
# "子词前缀命中"保守归一，只收无歧义的领域词根；want/interest 类要求宾语
# 是岗位（同 ROLE_ONLY_SOURCES 语义），公司宾语一律放行走 per_object 兜底。
# 条目 = (必备子词组, 目标谓词, 是否要求岗位宾语)；顺序即优先级。
_SUBWORD_FALLBACK: list[tuple[tuple[str, ...], str, bool]] = [
    (("familiar",), "uses", False),
    (("skill",), "uses", False),
    (("proficient",), "uses", False),
    (("name",), "name", False),
    (("prefer", "location"), "prefers_city", False),
    (("prefer", "city"), "prefers_city", False),
    (("want", "apply"), "target_role", True),
    (("interest",), "target_role", True),
]


def _subword_map(src: str, obj: str) -> Optional[str]:
    """亚词兜底：必备子词按前缀命中谓词的分词；不命中返回 None（原样保留）。"""
    tokens = src.lower().split("_")
    for required, target, role_only in _SUBWORD_FALLBACK:
        if all(any(t.startswith(r) for t in tokens) for r in required):
            if role_only and not is_role_like(obj):
                return None
            return target
    return None


# 状态类亚词兜底（谓词亚词未命中后触发）：LLM 会把"挂了/被拒"造出词典外的
# 失败类变体——v4 探针实测同一输入"滴滴挂了"5 次调用产出 4 种谓词
# （failed_at / was_rejected_by / failed_interview_at / failed_application），
# 其中 failed_application 词典未登记。按失败类词根归一为 ended 状态改写。
_SUBWORD_STATUS: list[tuple[tuple[str, ...], str]] = [
    (("fail",), "ended"),
    (("reject",), "ended"),
]


def _subword_status(src: str) -> Optional[str]:
    tokens = src.lower().split("_")
    for required, status in _SUBWORD_STATUS:
        if all(any(t.startswith(r) for t in tokens) for r in required):
            return status
    return None

# 实体归一化作用的谓词（object 是公司名）
_COMPANY_SCOPED = {"applied_to", "withdrawn", "works_at"}
# negative 极性下应改写为撤销留档的谓词
_RETRACTABLE = {"applied_to", "application_status"}


def normalize_fact(fact: ExtractedFact) -> ExtractedFact:
    """单条事实归一化。返回新对象，不修改输入（除伴随补全外的全部改写）。"""
    src = fact.predicate
    pred, obj = src, fact.object

    # 1) 状态类自由谓词 -> application_status:{实体}:{状态}
    if src in STATUS_ALIASES:
        pred = "application_status"
        obj = f"{_norm_company(obj)}:{STATUS_ALIASES[src]}"
    # 2) 谓词别名（岗位条件条目按宾语判定）
    elif src in PREDICATE_ALIASES:
        if src not in ROLE_ONLY_SOURCES or is_role_like(obj):
            pred = PREDICATE_ALIASES[src]
    # 2.5) 亚词兜底：词典未命中的非规范谓词按语义词根归一
    elif src not in _CANONICAL:
        mapped = _subword_map(src, obj)
        if mapped:
            pred = mapped
        else:
            status = _subword_status(src)
            if status:
                pred = "application_status"
                obj = f"{_norm_company(obj)}:{status}"

    # 3) 宾语感知：投递/偏好谓词 + 岗位宾语 -> target_role
    #    （"改投后端岗"的"改"语义，M20 实测；prefers+岗位宾语=目标岗位偏好，
    #    v4 U01 实测"我想投后端岗"被抽成 prefers——岗位宾语是唯一判据，
    #    非岗位宾语的偏好（"更喜欢远程办公"）不动）
    if pred in ("applied_to", "prefers") and is_role_like(_fold_role(obj)):
        pred = "target_role"

    # 4) 极性修正：撤销/否定走 withdrawn 留档（ops 凭 polarity 触发撤销路径，
    #    谓词规范化让"撤销了什么"在审计与检索语义上都正确）
    if fact.polarity == "negative" and pred in _RETRACTABLE:
        pred, obj = "withdrawn", obj.split(":", 1)[0]

    # 5) 实体归一化（公司域谓词；application_status 只归一实体段）
    if pred in _COMPANY_SCOPED and obj:
        obj = _norm_company(obj) or obj
    elif pred == "application_status":
        entity, sep, st = obj.partition(":")
        obj = f"{(_norm_company(entity) or entity)}{sep}{st}"
    elif pred == "target_role":
        # 6) 岗位宾语规范（见 _fold_role：v3"岗位→岗" + v4"开发/工程师"嵌入缀）
        obj = _fold_role(obj)

    return ExtractedFact(
        subject=fact.subject,
        predicate=pred,
        object=obj,
        category=PREDICATE_CATEGORY.get(pred, fact.category),
        confidence=fact.confidence,
        polarity=fact.polarity,
        mentioned_text=fact.mentioned_text,
        rule=f"norm:{src}" if src != pred else fact.rule,
    )


def normalize_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    """批量归一化：逐条改写 + 三元组去重 + 投递隐含状态伴随补全。

    伴随补全对齐规则版 _f_applied 的不变量（投递必产 applied_to +
    application_status:{实体}:submitted 两条）：LLM 只抽 applied_to 时，
    下游"流程状态"意图查询会失效（v2 对比 9/20 的差异源）。
    """
    out: list[ExtractedFact] = []
    seen: set[tuple[str, str, str]] = set()
    for f in facts:
        nf = normalize_fact(f)
        if nf.triple_key in seen:
            continue
        seen.add(nf.triple_key)
        out.append(nf)

    has_status = {
        f.object.split(":", 1)[0]
        for f in out
        if f.predicate == "application_status" and f.polarity == "positive"
    }
    companions: list[ExtractedFact] = []
    for f in out:
        if not (f.predicate == "applied_to" and f.polarity == "positive"
                and f.object and f.object not in has_status):
            continue
        ckey = (f.subject, "application_status", f"{f.object}:submitted")
        if ckey in seen:  # 批内已有同实体状态，不重复补
            continue
        seen.add(ckey)
        companions.append(
            ExtractedFact(
                subject=f.subject,
                predicate="application_status",
                object=f"{f.object}:submitted",
                category="application",
                confidence=f.confidence,
                polarity="positive",
                mentioned_text=f.mentioned_text,
                rule="normalize_companion",
            )
        )
    out.extend(companions)
    return out
