"""normalize.py：谓词映射层——LLM 自由谓词/实体到规范词典的确定性归一化。

用例按 eval_set100 真模型对比的实测证据组织（U01/W03/W05/W09/M20 等），
每条用例先还原 LLM 的原始输出形状，再断言归一结果与规则版抽取一致。
"""

from __future__ import annotations

import httpx

from memomind.extract import OpenAICompatibleExtractor
from memomind.llm import OpenAICompatibleClient
from memomind.normalize import normalize_fact, normalize_facts
from memomind.schema import ExtractedFact


def _fact(pred: str, obj: str, *, polarity: str = "positive",
          category: str = "other", confidence: float = 0.9) -> ExtractedFact:
    return ExtractedFact("user", pred, obj, category, confidence, polarity=polarity)


def _triples(facts: list[ExtractedFact]) -> set[tuple[str, str]]:
    return {(f.predicate, f.object) for f in facts}


# -- 谓词别名映射（差异类①：谓词命名 16/20）---------------------------------
def test_has_skill_maps_to_uses():
    f = normalize_fact(_fact("has_skill", "Python"))
    assert (f.predicate, f.object, f.category) == ("uses", "Python", "skill")


def test_has_name_maps_to_name():
    f = normalize_fact(_fact("has_name", "王芳"))
    assert (f.predicate, f.object, f.category) == ("name", "王芳", "identity")


def test_wants_to_work_in_maps_to_prefers_city():
    f = normalize_fact(_fact("wants_to_work_in", "广州"))
    assert (f.predicate, f.object, f.category) == ("prefers_city", "广州", "preference")


def test_role_only_alias_with_role_object():
    # U01：wants_to_apply_to + 岗位宾语 -> target_role
    f = normalize_fact(_fact("wants_to_apply_to", "后端岗"))
    assert (f.predicate, f.object) == ("target_role", "后端岗")


def test_role_only_alias_with_company_object_kept():
    # 公司宾语的"想投"不是目标岗位，也不是"已投"——保留原谓词走 per_object 兜底
    f = normalize_fact(_fact("wants_to_apply_to", "字节跳动"))
    assert f.predicate == "wants_to_apply_to"


# -- 亚词兜底（v3 复测发现词典枚举盲区：LLM 运行间造同义变体）----------------
def test_subword_familiar_with_maps_to_uses():
    # v3 实测：is_familiar_with（v2 用的是 has_skill）
    f = normalize_fact(_fact("is_familiar_with", "Python"))
    assert (f.predicate, f.object) == ("uses", "Python")


def test_subword_prefers_work_location_maps_to_prefers_city():
    # v3 实测：prefers_work_location（v2 用的是 wants_to_work_in）
    f = normalize_fact(_fact("prefers_work_location", "广州"))
    assert (f.predicate, f.object) == ("prefers_city", "广州")


def test_subword_wants_to_apply_role_object():
    # v3 实测：wants_to_apply（少个 _to）+ 岗位宾语 -> target_role
    f = normalize_fact(_fact("wants_to_apply", "测试岗"))
    assert (f.predicate, f.object) == ("target_role", "测试岗")


def test_subword_wants_to_apply_company_object_kept():
    f = normalize_fact(_fact("wants_to_apply", "字节跳动"))
    assert f.predicate == "wants_to_apply"


def test_subword_no_fire_without_required_token():
    # "work_location" 缺偏好词根，不放猜测——原样保留
    f = normalize_fact(_fact("work_location", "杭州"))
    assert f.predicate == "work_location"


# -- 宾语规范（v3 复测残差：LLM 展开岗位缩写）--------------------------------
def test_target_role_object_suffix_fold():
    # U01 v3 实测：interested_in 后端岗位 -> target_role 后端岗
    f = normalize_fact(_fact("interested_in", "后端岗位"))
    assert (f.predicate, f.object) == ("target_role", "后端岗")


def test_target_role_object_whitespace_stripped():
    f = normalize_fact(_fact("target_role", "Agent 岗"))
    assert f.object == "Agent岗"


# -- 状态类谓词改写（W05/W09）------------------------------------------------
def test_received_offer_maps_to_status_offer():
    f = normalize_fact(_fact("received_offer_from", "字节跳动"))
    assert (f.predicate, f.object, f.category) == ("application_status", "字节跳动:offer", "application")


def test_was_rejected_maps_to_status_ended_with_entity_norm():
    # W09：was_rejected_by + LLM 全称"滴滴出行" -> 规范实体 + ended
    f = normalize_fact(_fact("was_rejected_by", "滴滴出行"))
    assert (f.predicate, f.object) == ("application_status", "滴滴:ended")


def test_failed_interview_at_maps_to_ended():
    # v1 实测证据："没过一面" -> failed_interview_at
    f = normalize_fact(_fact("failed_interview_at", "字节跳动"))
    assert f.object == "字节跳动:ended"


# -- 宾语感知改写（M20 真实误抽）---------------------------------------------
def test_applied_to_with_role_object_maps_to_target_role():
    # M20："改投后端岗了"被 LLM 抽成 applied_to 后端岗——岗位不是公司
    f = normalize_fact(_fact("applied_to", "后端岗"))
    assert (f.predicate, f.object) == ("target_role", "后端岗")
    # 且不产生伴随状态（岗位没有投递状态）
    assert _triples(normalize_facts([_fact("applied_to", "后端岗")])) == {("target_role", "后端岗")}


def test_applied_for_variant_maps():
    f = normalize_fact(_fact("applied_for", "美团"))
    assert f.predicate == "applied_to"


# -- 极性修正（差异类③：W03/W04 否定极性错挂谓词）---------------------------
def test_negative_applied_to_becomes_withdrawn():
    # W03/W04：LLM 抽 applied_to + negative，规范化为 withdrawn 留档
    f = normalize_fact(_fact("applied_to", "阿里巴巴", polarity="negative"))
    assert (f.predicate, f.object, f.polarity, f.category) == (
        "withdrawn", "阿里巴巴", "negative", "application")


def test_negative_application_status_becomes_withdrawn():
    f = normalize_fact(_fact("application_status", "腾讯:submitted", polarity="negative"))
    assert (f.predicate, f.object, f.polarity) == ("withdrawn", "腾讯", "negative")


def test_positive_status_not_retracted():
    f = normalize_fact(_fact("application_status", "字节跳动:offer"))
    assert f.predicate == "application_status"


# -- 实体归一化（差异类④：W09 分叉）-----------------------------------------
def test_company_alias_normalization_on_llm_output():
    f = normalize_fact(_fact("applied_to", "字节"))
    assert f.object == "字节跳动"


def test_application_status_entity_segment_normalized():
    f = normalize_fact(_fact("application_status", "滴滴出行:submitted"))
    assert f.object == "滴滴:submitted"


# -- 伴随补全（差异类②：隐含状态 9/20）--------------------------------------
def test_companion_status_synthesized():
    out = normalize_facts([_fact("applied_to", "美团")])
    assert _triples(out) == {("applied_to", "美团"), ("application_status", "美团:submitted")}
    assert out[1].rule == "normalize_companion"
    assert out[1].confidence == out[0].confidence


def test_companion_skipped_when_status_present():
    out = normalize_facts([_fact("applied_to", "字节跳动"),
                           _fact("application_status", "字节跳动:offer")])
    assert ("application_status", "字节跳动:submitted") not in _triples(out)


def test_no_companion_for_negative_or_role():
    out = normalize_facts([_fact("applied_to", "阿里巴巴", polarity="negative"),
                           _fact("applied_to", "后端岗")])
    assert _triples(out) == {("withdrawn", "阿里巴巴"), ("target_role", "后端岗")}


def test_dedupe_after_mapping():
    # has_skill 与 knows 同宾语 -> 同一规范三元组只留一条
    out = normalize_facts([_fact("has_skill", "Python"), _fact("knows", "Python")])
    assert len(out) == 1


def test_unknown_predicate_passthrough():
    # 未登记谓词原样保留（ops 的 per_object 兜底），category 不强行改写
    f = normalize_fact(_fact("prefers_remote_work", "远程办公", category="preference"))
    assert (f.predicate, f.object, f.category) == ("prefers_remote_work", "远程办公", "preference")


# -- 端到端：LLM 原始输出 -> 规范事实（MockTransport，无网络）-----------------
def _llm_extractor(content: str) -> OpenAICompatibleExtractor:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return OpenAICompatibleExtractor(client=OpenAICompatibleClient(
        base_url="http://test", api_key="k", model="m", transport=httpx.MockTransport(handler)))


def _json_of(*facts: dict) -> str:
    import json

    return json.dumps({"facts": list(facts)}, ensure_ascii=False)


def test_end_to_end_free_predicates_normalized():
    # 还原 v2 对比里 W03/W05/W09/M20 四类差异的 LLM 原始输出
    content = _json_of(
        {"subject": "user", "predicate": "applied_to", "object": "阿里巴巴",
         "category": "application", "confidence": 1.0, "polarity": "negative"},
        {"subject": "user", "predicate": "received_offer_from", "object": "字节跳动",
         "category": "event", "confidence": 1.0, "polarity": "positive"},
        {"subject": "user", "predicate": "was_rejected_by", "object": "滴滴出行",
         "category": "event", "confidence": 1.0, "polarity": "positive"},
        {"subject": "user", "predicate": "applied_to", "object": "后端岗",
         "category": "application", "confidence": 1.0, "polarity": "positive"},
    )
    ex = _llm_extractor(content)
    facts = ex.extract("取消阿里的申请，收到字节的offer，滴滴挂了，改投后端岗了")
    assert _triples(facts) == {
        ("withdrawn", "阿里巴巴"),
        ("application_status", "字节跳动:offer"),
        ("application_status", "滴滴:ended"),
        ("target_role", "后端岗"),
    }
    # 原始事实留痕：4 条，谓词未被归一
    assert {f.predicate for f in ex.last_raw_facts} == {
        "applied_to", "received_offer_from", "was_rejected_by"}


def test_end_to_end_applied_companion_matches_rule_extractor():
    # "我投了字节跳动"：LLM 只抽 applied_to，归一后与规则版伴随对完全一致
    content = _json_of(
        {"subject": "user", "predicate": "applied_to", "object": "字节跳动",
         "category": "application", "confidence": 1.0, "polarity": "positive"})
    ex = _llm_extractor(content)
    facts = ex.extract("我投了字节跳动")
    from memomind.extract import RuleExtractor

    rule = {(f.predicate, f.object) for f in RuleExtractor().extract("我投了字节跳动")}
    assert _triples(facts) == rule
    assert len(ex.last_raw_facts) == 1  # last_raw_facts 保存未归一输出


# -- v4 增量修订（MM-3：第一轮 v4 复测的两条新变体，条目全部来自实测证据）------
def test_deepseek_chinese_name_alias():
    # v4 A05 实测：LLM 把 "deepseek" 翻译成官方中文名"深度求索"
    f = normalize_fact(_fact("applied_to", "深度求索", category="application"))
    assert (f.predicate, f.object) == ("applied_to", "DeepSeek")
    facts = normalize_facts([_fact("applied_to", "深度求索", category="application")])
    assert _triples(facts) == {("applied_to", "DeepSeek"),
                               ("application_status", "DeepSeek:submitted")}


def test_role_object_folds_embedded_dev_suffix():
    # v4 U01 实测：LLM 抽 (prefers, 后端开发岗位)——岗位宾语折迭后判为 target_role
    f = normalize_fact(_fact("prefers", "后端开发岗位", category="preference"))
    assert (f.predicate, f.object) == ("target_role", "后端岗")


def test_applied_to_compound_role_object_becomes_target_role():
    # 同一折迭也修 applied_to + 复合岗位宾语（"投后端开发岗"不是投公司）
    f = normalize_fact(_fact("applied_to", "后端开发岗", category="application"))
    assert (f.predicate, f.object) == ("target_role", "后端岗")


def test_prefers_non_role_object_untouched():
    # 红线守卫：非岗位宾语的偏好不动（"更喜欢远程办公"不是目标岗位）
    f = normalize_fact(_fact("prefers", "远程办公", category="preference"))
    assert (f.predicate, f.object) == ("prefers", "远程办公")


def test_role_object_engineer_suffix_preserved():
    # "算法工程师"是合法岗位写法（无"岗"结尾），折迭不动它
    f = normalize_fact(_fact("target_role", "算法工程师", category="preference"))
    assert (f.predicate, f.object) == ("target_role", "算法工程师")


def test_bare_dev_word_not_folded_to_empty():
    # 宾语本身只有"开发/工程师"时不折成空串（is_role_like("开发") 仍成立）
    f = normalize_fact(_fact("target_role", "开发", category="preference"))
    assert (f.predicate, f.object) == ("target_role", "开发")


def test_failed_application_variant_maps_to_ended():
    # v4 探针实测：同一输入"滴滴挂了"5 次调用产出 4 种谓词变体，其中
    # failed_application 词典未登记——失败类亚词兜底归一为 ended 状态改写
    f = normalize_fact(_fact("failed_application", "滴滴出行", confidence=0.95))
    assert (f.predicate, f.object) == ("application_status", "滴滴:ended")


def test_reject_root_subword_status():
    f = normalize_fact(_fact("rejected_by_application", "美团"))
    assert (f.predicate, f.object) == ("application_status", "美团:ended")
