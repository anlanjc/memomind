"""生成 evals/eval_set_100.json：100 条跨会话用例，5 层 × 20 条（v2 扩容）。

v1（scenarios.py，20 条）的扩容版，分层口径按评测目标重划：
- U 事实更新 20：单值属性更替 / 重复强化 / 多值并存 / 多步更替链
- W 冲突撤回 20：状态机更替（submitted→interviewing→offer→ended）/ 撤销型事实 /
  撤销后重投 / 无中生有的撤销
- A 别名归一 20：公司短称↔全称、岗位后缀剥离——归一前是两条记忆，归一后正确冲突
- D 时序衰减 20：过期归档 / 衰减归档 / 访问刷新抗遗忘 / compaction 物理清理 / 差分衰减
- M 多跳召回 20：图邻域 / 意图映射 / 状态+历史联动 / 撤回与替代后检索不可见

期望全部对着 RuleExtractor 的规则表、RuleOpsDecider 的决策矩阵与
DecayConfig(half_life=30, min_eff=0.15) 的公式推得，mock 跑通即金标自洽。

用法：python evals/build_eval_set100.py   （在项目根目录）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def s(text: str = "", session: str = "s1", advance: float = 0.0,
      decay: bool = False, compact: bool = False, seeds: list | None = None) -> dict:
    return dict(session=session, text=text, advance_days=advance,
                run_decay=decay, run_compact=compact, seeds=seeds or [])


def seed(subject: str, predicate: str, obj: str, category: str,
         conf: float, valid_to_days: float | None = None) -> list:
    return [subject, predicate, obj, category, conf, valid_to_days]


def c(sid: str, layer: str, title: str, steps: list[dict], **expect) -> dict:
    return dict(sid=sid, layer=layer, title=title, steps=steps, expect=expect)


CASES: list[dict] = []

# ===========================================================================
# U 事实更新（20）
# ===========================================================================
CASES += [
    c("U01", "事实更新", "目标岗位 后端→Agent（单值更替）",
      [s("我想投后端岗"), s("改投 Agent 岗了", session="s2")],
      active=[["target_role", "Agent岗"]], superseded=[["target_role", "后端岗"]],
      count_active_pred={"target_role": 1}),

    c("U02", "事实更新", "目标岗位 Agent→算法（转向措辞）",
      [s("想投 Agent 岗"), s("转向算法", session="s2")],
      active=[["target_role", "算法"]], superseded=[["target_role", "Agent岗"]]),

    c("U03", "事实更新", "期望城市 北京→杭州",
      [s("我想去北京工作"), s("我想去杭州工作", session="s2")],
      active=[["prefers_city", "杭州"]], superseded=[["prefers_city", "北京"]]),

    c("U04", "事实更新", "期望城市 上海→成都（搬家措辞）",
      [s("我想去上海工作"), s("想搬到成都", session="s2")],
      active=[["prefers_city", "成都"]], superseded=[["prefers_city", "上海"]]),

    c("U05", "事实更新", "在职公司 美团→字节",
      [s("我现在在美团工作"), s("我现在在字节工作", session="s2")],
      active=[["works_at", "字节跳动"]], superseded=[["works_at", "美团"]]),

    c("U06", "事实更新", "在职公司 华为→腾讯（上班措辞）",
      [s("我现在在华为工作"), s("我现在在腾讯上班", session="s2")],
      active=[["works_at", "腾讯"]], superseded=[["works_at", "华为"]]),

    c("U07", "事实更新", "姓名 李雷→韩梅梅（functional 谓词更替）",
      [s("我叫李雷"), s("我叫韩梅梅", session="s2")],
      active=[["name", "韩梅梅"]], superseded=[["name", "李雷"]]),

    c("U08", "事实更新", "重复技能 熟悉→掌握（B1 强化而非新增）",
      [s("我熟悉 Python"), s("我掌握 Python", session="s2")],
      active=[["uses", "Python"]], count_active_pred={"uses": 1},
      ops_last_any=[{"op": "UPDATE", "update_kind": "strengthen"}],
      conf_gt=[["uses", "Python", 0.88]]),

    c("U09", "事实更新", "完全重复投递（B2 NOOP 不落重复记忆）",
      [s("我投了腾讯"), s("我投了腾讯", session="s2")],
      active=[["applied_to", "腾讯"], ["application_status", "腾讯:submitted"]],
      count_active_pred={"applied_to": 1},
      ops_last_any=[{"op": "NOOP"}]),

    c("U10", "事实更新", "一次投两家 美团和快手（多值并存）",
      [s("我投了美团和快手")],
      active=[["applied_to", "美团"], ["applied_to", "快手"],
              ["application_status", "美团:submitted"], ["application_status", "快手:submitted"]],
      count_active_pred={"applied_to": 2}),

    c("U11", "事实更新", "新增偏好 远程办公",
      [s("我更喜欢远程办公")],
      active=[["prefers", "远程办公"]]),

    c("U12", "事实更新", "目标岗位 后端→Agent（改投措辞）",
      [s("目标是后端"), s("想改投 Agent 岗", session="s2")],
      active=[["target_role", "Agent岗"]], superseded=[["target_role", "后端"]]),

    c("U13", "事实更新", "期望城市 深圳→成都（打算去措辞）",
      [s("打算去深圳工作"), s("我想去成都工作", session="s2")],
      active=[["prefers_city", "成都"]], superseded=[["prefers_city", "深圳"]]),

    c("U14", "事实更新", "同一公司两种说法重复投递（归一后 B2 NOOP）",
      [s("我投了字节跳动"), s("我投了字节", session="s2")],
      active=[["applied_to", "字节跳动"]],
      count_active_pred={"applied_to": 1}, ops_last_any=[{"op": "NOOP"}]),

    c("U15", "事实更新", "一次报三个技能（多值谓词各落一条）",
      [s("我熟悉 Python、FastAPI 和 MySQL")],
      active=[["uses", "Python"], ["uses", "FastAPI"], ["uses", "MySQL"]],
      count_active_pred={"uses": 3}),

    c("U16", "事实更新", "一句话两个事实（姓名+目标岗位）",
      [s("我叫王芳，我想投测试岗")],
      active=[["name", "王芳"], ["target_role", "测试岗"]], count_active=2),

    c("U17", "事实更新", "城市三连更替 北京→上海→广州",
      [s("我想去北京工作"), s("我想去上海工作", session="s2"), s("我想去广州工作", session="s3")],
      active=[["prefers_city", "广州"]],
      superseded=[["prefers_city", "北京"], ["prefers_city", "上海"]]),

    c("U18", "事实更新", "城市改回原地 北京→杭州→北京",
      [s("我想去北京工作"), s("我想去杭州工作", session="s2"), s("我想去北京工作", session="s3")],
      active=[["prefers_city", "北京"]], superseded=[["prefers_city", "杭州"]]),

    c("U19", "事实更新", "目标岗位无后缀→带工程师后缀",
      [s("想投后端"), s("想投算法工程师", session="s2")],
      active=[["target_role", "算法工程师"]], superseded=[["target_role", "后端"]]),

    c("U20", "事实更新", "偏好两条并存（per_object 不冲突）",
      [s("我更喜欢大厂"), s("我更喜欢远程办公", session="s2")],
      active=[["prefers", "大厂"], ["prefers", "远程办公"]],
      count_active_pred={"prefers": 2}),
]

# ===========================================================================
# W 冲突撤回（20）
# ===========================================================================
CASES += [
    c("W01", "冲突撤回", "投递→流程结束（状态替代，历史保留）",
      [s("我投了字节跳动"), s("字节流程结束了", session="s2")],
      active=[["application_status", "字节跳动:ended"], ["applied_to", "字节跳动"]],
      superseded=[["application_status", "字节跳动:submitted"]]),

    c("W02", "冲突撤回", "面试中→挂了",
      [s("收到字节的面试邀请"), s("字节挂了", session="s2")],
      active=[["application_status", "字节跳动:ended"]],
      superseded=[["application_status", "字节跳动:interviewing"]]),

    c("W03", "冲突撤回", "取消申请（撤销型事实失效投递记忆）",
      [s("我投了阿里巴巴"), s("取消阿里的申请", session="s2")],
      active=[["withdrawn", "阿里巴巴"]],
      superseded=[["applied_to", "阿里巴巴"], ["application_status", "阿里巴巴:submitted"]]),

    c("W04", "冲突撤回", "无中生有的撤销（撤销意图留档）",
      [s("不想投腾讯了")],
      active=[["withdrawn", "腾讯"]]),

    c("W05", "冲突撤回", "投递→拿 offer",
      [s("我投了字节跳动"), s("收到字节的offer", session="s2")],
      active=[["application_status", "字节跳动:offer"]],
      superseded=[["application_status", "字节跳动:submitted"]]),

    c("W06", "冲突撤回", "撤回两家投递中的一家（另一家不受影响）",
      [s("我投了美团和快手"), s("取消快手的申请", session="s2")],
      active=[["applied_to", "美团"], ["application_status", "美团:submitted"],
              ["withdrawn", "快手"]],
      superseded=[["applied_to", "快手"], ["application_status", "快手:submitted"]]),

    c("W07", "冲突撤回", "状态三连 ended→新面试（复活合法化）",
      [s("我投了字节跳动"), s("字节流程结束了", session="s2"),
       s("收到字节的面试邀请", session="s3")],
      active=[["application_status", "字节跳动:interviewing"]],
      superseded=[["application_status", "字节跳动:submitted"],
                  ["application_status", "字节跳动:ended"]]),

    c("W08", "冲突撤回", "在职公司 字节→阿里（矛盾替代）",
      [s("我现在在字节工作"), s("我现在在阿里工作", session="s2")],
      active=[["works_at", "阿里巴巴"]], superseded=[["works_at", "字节跳动"]]),

    c("W09", "冲突撤回", "裸挂了陈述（company2 分支）",
      [s("滴滴挂了")],
      active=[["application_status", "滴滴:ended"]]),

    c("W10", "冲突撤回", "撤销后重投同一公司（新投递生效，撤销留档）",
      [s("我投了腾讯"), s("取消腾讯的申请", session="s2"), s("我又投了腾讯", session="s3")],
      active=[["applied_to", "腾讯"], ["application_status", "腾讯:submitted"],
              ["withdrawn", "腾讯"]],
      superseded=[["applied_to", "腾讯"]]),

    c("W11", "冲突撤回", "重复撤销同一公司（C1 无去重，重复留档）",
      [s("我投了京东"), s("取消京东的申请", session="s2"), s("不想投京东了", session="s3")],
      active=[["withdrawn", "京东"]],
      superseded=[["applied_to", "京东"], ["application_status", "京东:submitted"]],
      count_active_pred={"withdrawn": 2}, ops_last_any=[{"op": "ADD"}]),

    c("W12", "冲突撤回", "直接说挂了（无投递前置）",
      [s("字节挂了")],
      active=[["application_status", "字节跳动:ended"]]),

    c("W13", "冲突撤回", "面试→offer→结束（状态机三跳）",
      [s("收到美团的面试邀请"), s("收到美团的offer", session="s2"),
       s("美团流程结束了", session="s3")],
      active=[["application_status", "美团:ended"]],
      superseded=[["application_status", "美团:interviewing"],
                  ["application_status", "美团:offer"]]),

    c("W14", "冲突撤回", "短称撤销全称投递（归一后命中撤销目标）",
      [s("我投了字节跳动"), s("取消字节的申请", session="s2")],
      active=[["withdrawn", "字节跳动"]],
      superseded=[["applied_to", "字节跳动"]]),

    c("W15", "冲突撤回", "三家公司只挂一家（其余不受影响）",
      [s("我投了腾讯和阿里"), s("我投了字节", session="s1b"),
       s("阿里的流程结束了", session="s2")],
      active=[["application_status", "腾讯:submitted"], ["application_status", "阿里巴巴:ended"],
              ["application_status", "字节跳动:submitted"],
              ["applied_to", "腾讯"], ["applied_to", "阿里巴巴"], ["applied_to", "字节跳动"]],
      superseded=[]),

    c("W16", "冲突撤回", "面试后取消申请",
      [s("我投了美团"), s("收到美团的面试邀请", session="s2"),
       s("取消美团的申请", session="s3")],
      active=[["withdrawn", "美团"]],
      superseded=[["applied_to", "美团"], ["application_status", "美团:submitted"],
                  ["application_status", "美团:interviewing"]]),

    c("W17", "冲突撤回", "姓名冲突 小明→小红",
      [s("我叫小明"), s("我叫小红", session="s2")],
      active=[["name", "小红"]], superseded=[["name", "小明"]]),

    c("W18", "冲突撤回", "目标岗位三连 后端→Agent→大模型",
      [s("想投后端岗"), s("改投 Agent 岗了", session="s2"), s("主要投大模型", session="s3")],
      active=[["target_role", "大模型"]],
      superseded=[["target_role", "后端岗"], ["target_role", "Agent岗"]]),

    c("W19", "冲突撤回", "面试邀请后放弃投递",
      [s("收到字节的面试邀请"), s("不想投字节了", session="s2")],
      active=[["withdrawn", "字节跳动"]],
      superseded=[["application_status", "字节跳动:interviewing"]]),

    c("W20", "冲突撤回", "拿到 offer 后取消（撤销命中 offer 状态）",
      [s("收到美团的offer"), s("取消美团的申请", session="s2")],
      active=[["withdrawn", "美团"]],
      superseded=[["application_status", "美团:offer"]]),
]

# ===========================================================================
# A 别名归一（20）
# ===========================================================================
CASES += [
    c("A01", "别名归一", "字节→字节跳动 归一后状态替代",
      [s("我投了字节"), s("字节跳动的流程结束了", session="s2")],
      active=[["application_status", "字节跳动:ended"]],
      superseded=[["application_status", "字节跳动:submitted"]],
      count_active_pred={"application_status": 1}),

    c("A02", "别名归一", "阿里巴巴→阿里 撤销命中",
      [s("我投了阿里巴巴"), s("取消阿里的申请", session="s2")],
      active=[["withdrawn", "阿里巴巴"]],
      superseded=[["applied_to", "阿里巴巴"]]),

    c("A03", "别名归一", "蚂蚁→蚂蚁集团",
      [s("我投了蚂蚁"), s("蚂蚁的流程结束了", session="s2")],
      active=[["application_status", "蚂蚁集团:ended"]],
      superseded=[["application_status", "蚂蚁集团:submitted"]]),

    c("A04", "别名归一", "岗位后缀剥离 字节的Agent岗→字节跳动",
      [s("我投了字节的Agent岗")],
      active=[["applied_to", "字节跳动"], ["application_status", "字节跳动:submitted"]]),

    c("A05", "别名归一", "小写 deepseek→DeepSeek",
      [s("投了deepseek"), s("我投过哪些公司？", session="s2")],
      active=[["applied_to", "DeepSeek"]],
      recall_contains=["DeepSeek"]),

    c("A06", "别名归一", "同公司短称/全称状态接续",
      [s("我投了快手"), s("收到快手的面试邀请", session="s2")],
      active=[["application_status", "快手:interviewing"]],
      superseded=[["application_status", "快手:submitted"]]),

    c("A07", "别名归一", "后端岗后缀剥离",
      [s("我投了字节的后端岗")],
      active=[["applied_to", "字节跳动"]]),

    c("A08", "别名归一", "一句投两家 短称归一",
      [s("我投了阿里和字节")],
      active=[["applied_to", "阿里巴巴"], ["applied_to", "字节跳动"]],
      count_active_pred={"applied_to": 2}),

    c("A09", "别名归一", "裸挂了短称归一",
      [s("字节挂了")],
      active=[["application_status", "字节跳动:ended"]]),

    c("A10", "别名归一", "在职短称→短称 矛盾替代",
      [s("我现在在美团上班"), s("我现在在字节上班", session="s2")],
      active=[["works_at", "字节跳动"]], superseded=[["works_at", "美团"]]),

    c("A11", "别名归一", "全称→全称 在职更替",
      [s("我在网易工作"), s("我在字节跳动工作", session="s2")],
      active=[["works_at", "字节跳动"]], superseded=[["works_at", "网易"]]),

    c("A12", "别名归一", "面试邀请短称归一",
      [s("收到蚂蚁的面试邀请")],
      active=[["application_status", "蚂蚁集团:interviewing"]]),

    c("A13", "别名归一", "不想投短称→归一撤销",
      [s("不想投字节了")],
      active=[["withdrawn", "字节跳动"]]),

    c("A14", "别名归一", "全称/短称重复投递（归一后同一事实）",
      [s("我投了字节跳动"), s("我投了字节", session="s2")],
      active=[["applied_to", "字节跳动"]], count_active_pred={"applied_to": 1},
      ops_last_any=[{"op": "NOOP"}]),

    c("A15", "别名归一", "offer 短称归一",
      [s("收到字节的offer")],
      active=[["application_status", "字节跳动:offer"]]),

    c("A16", "别名归一", "短称查询召回全称记忆",
      [s("我投了阿里"), s("阿里的进展？", session="s2")],
      active=[["applied_to", "阿里巴巴"], ["application_status", "阿里巴巴:submitted"]],
      recall_contains=["阿里巴巴"]),

    c("A17", "别名归一", "全称投递→短称挂了",
      [s("我投了字节跳动"), s("字节挂了", session="s2")],
      active=[["application_status", "字节跳动:ended"]],
      superseded=[["application_status", "字节跳动:submitted"]]),

    c("A18", "别名归一", "在职记忆意图召回",
      [s("我在华为工作"), s("我现在在哪家公司？", session="s2")],
      active=[["works_at", "华为"]],
      recall_top="华为"),

    c("A19", "别名归一", "两家短称投递撤一家",
      [s("我投了字节和阿里"), s("取消阿里的申请", session="s2")],
      active=[["applied_to", "字节跳动"], ["application_status", "字节跳动:submitted"],
              ["withdrawn", "阿里巴巴"]],
      superseded=[["applied_to", "阿里巴巴"]]),

    c("A20", "别名归一", "岗位后缀变体 Agent岗位",
      [s("我投了字节的Agent岗位")],
      active=[["applied_to", "字节跳动"]]),
]

# ===========================================================================
# D 时序衰减（20）
# ===========================================================================
CASES += [
    c("D01", "时序衰减", "120 天无人问津 → 衰减归档且不再干扰检索",
      [s("我投了滴滴"), s(advance=120, decay=True), s("我现在该投什么公司？", session="s2")],
      archived=[["applied_to", "滴滴"]],
      recall_not_contains=["滴滴"]),

    c("D02", "时序衰减", "带 valid_to 的实习到期归档",
      [s(seeds=[seed("user", "works_at", "创业公司X", "identity", 0.9, 90)]),
       s(advance=100, decay=True), s("我现在在哪家公司？", session="s2")],
      archived=[["works_at", "创业公司X"]],
      recall_not_contains=["创业公司X"]),

    c("D03", "时序衰减", "中途被想起 → 访问刷新时钟跨 90 天存活",
      [s("我叫李雷"), s("我叫什么名字？", session="s2", advance=45),
       s(advance=45, decay=True), s("我叫什么名字？", session="s3")],
      active=[["name", "李雷"]], recall_contains=["李雷"]),

    c("D04", "时序衰减", "superseded 超 30 天保留期 → compaction 物理清理",
      [s("我想投后端岗"), s("改投 Agent 岗了", session="s2"),
       s(advance=40, compact=True)],
      gone=[["target_role", "后端岗"]], active=[["target_role", "Agent岗"]]),

    c("D05", "时序衰减", "差分衰减：低置信偏好先亡，姓名犹存",
      [s("我叫李雷"), s("我更喜欢大厂", session="s1b"),
       s(advance=75, decay=True), s("我叫什么名字？", session="s2")],
      active=[["name", "李雷"]], archived=[["prefers", "大厂"]],
      recall_contains=["李雷"], recall_not_contains=["大厂"]),

    c("D06", "时序衰减", "80 天空闲的投递恰好跌穿阈值",
      [s("我投了字节跳动"), s(advance=80, decay=True)],
      archived=[["applied_to", "字节跳动"]]),

    c("D07", "时序衰减", "50 天时被想起 → 再过 50 天仍存活",
      [s("我投了字节跳动"),
       s("我投过哪些公司？", session="s2", advance=50),
       s(advance=50, decay=True)],
      active=[["applied_to", "字节跳动"]]),

    c("D08", "时序衰减", "decay 幂等：重复跑不二次归档",
      [s("我投了滴滴"), s(advance=90, decay=True), s(advance=30, decay=True)],
      archived=[["applied_to", "滴滴"]], absent_active=[["applied_to", "滴滴"]]),

    c("D09", "时序衰减", "被撤销的投递超保留期 → compaction 清除",
      [s("我投了腾讯"), s("取消腾讯的申请", session="s2"), s(advance=40, compact=True)],
      gone=[["applied_to", "腾讯"]], active=[["withdrawn", "腾讯"]]),

    c("D10", "时序衰减", "归档记忆超 90 天保留期 → compaction 清除",
      [s(seeds=[seed("user", "works_at", "创业公司X", "identity", 0.9, 30)]),
       s(advance=40, decay=True), s(advance=100, compact=True)],
      gone=[["works_at", "创业公司X"]]),

    c("D11", "时序衰减", "衰减归档后重新投递 → 新记录生效旧记录留档",
      [s("我投了字节跳动"), s(advance=85, decay=True), s("我投了字节跳动", session="s2")],
      active=[["applied_to", "字节跳动"]], archived=[["applied_to", "字节跳动"]],
      count_active_pred={"applied_to": 1}),

    c("D12", "时序衰减", "valid_to 当天到期即归档（边界 >=）",
      [s(seeds=[seed("user", "works_at", "某大厂", "identity", 0.95, 30)]),
       s(advance=30, decay=True)],
      archived=[["works_at", "某大厂"]]),

    c("D13", "时序衰减", "无有效期的姓名 30 天不衰减",
      [s(seeds=[seed("user", "name", "李雷", "identity", 0.99, None)]),
       s(advance=30, decay=True)],
      active=[["name", "李雷"]]),

    c("D14", "时序衰减", "三次 30 天渐进衰减最终归档",
      [s("我投了字节跳动"),
       s(advance=30, decay=True), s(advance=30, decay=True), s(advance=30, decay=True)],
      archived=[["applied_to", "字节跳动"]]),

    c("D15", "时序衰减", "60 天时查询刷新 → 再 40 天仍存活",
      [s("我投了字节跳动"),
       s("字节的流程怎么样？", session="s2", advance=60),
       s(advance=40, decay=True)],
      active=[["applied_to", "字节跳动"], ["application_status", "字节跳动:submitted"]]),

    c("D16", "时序衰减", "先后投两家：旧的衰减归档、新的存活",
      [s("我投了字节跳动"), s("我投了美团", session="s2", advance=60),
       s(advance=40, decay=True), s("我投过哪些公司？", session="s3")],
      active=[["applied_to", "美团"]], archived=[["applied_to", "字节跳动"]],
      recall_contains=["美团"], recall_not_contains=["字节跳动"]),

    c("D17", "时序衰减", "衰减归档后再过 95 天 → compaction 清除",
      [s("我投了滴滴"), s(advance=90, decay=True), s(advance=95, compact=True)],
      gone=[["applied_to", "滴滴"]]),

    c("D18", "时序衰减", "78 天差分：0.85 置信技能归档，0.99 姓名存活",
      [s("我叫李雷"), s("我熟悉 Python", session="s1b"),
       s(advance=78, decay=True), s("我叫什么名字？", session="s2")],
      active=[["name", "李雷"]], archived=[["uses", "Python"]]),

    c("D19", "时序衰减", "衰减加权排序：新投递压过旧投递排第一",
      [s("我投了字节跳动"), s("我投了美团", session="s2", advance=40),
       s("我投过哪些公司？", session="s3", advance=10)],
      recall_top="美团", recall_contains=["美团", "字节跳动"]),

    c("D20", "时序衰减", "每 30 天被想起一次 → 跨 120 天存活",
      [s("我叫李雷"),
       s("我叫什么名字？", session="s2", advance=30),
       s("我叫什么名字？", session="s3", advance=30),
       s("我叫什么名字？", session="s4", advance=30),
       s(advance=30, decay=True)],
      active=[["name", "李雷"]]),
]

# ===========================================================================
# M 多跳召回（20）
# ===========================================================================
CASES += [
    c("M01", "多跳召回", "问流程带出投递历史（图邻域+意图）",
      [s("我投了字节跳动"), s("字节的流程怎么样？", session="s2")],
      recall_min=2, recall_contains=["字节跳动", "字节跳动:submitted"]),

    c("M02", "多跳召回", "问技能召回全部技能（意图映射）",
      [s("我熟悉 Python、FastAPI 和 MySQL"), s("我会什么技术栈？", session="s2")],
      recall_min=3, recall_contains=["Python", "FastAPI", "MySQL"]),

    c("M03", "多跳召回", "问投递召回两家公司",
      [s("我投了腾讯"), s("我投了字节跳动", session="s1b"),
       s("我投过哪些公司？", session="s2")],
      recall_min=2, recall_contains=["腾讯", "字节跳动"]),

    c("M04", "多跳召回", "偏好意图只命中偏好记忆",
      [s("我更喜欢大厂"), s("我想投后端岗", session="s1b"),
       s("我喜欢什么样的公司？", session="s2")],
      recall_top="大厂"),

    c("M05", "多跳召回", "问 offer 召回 offer 状态",
      [s("我投了字节跳动"), s("收到字节的offer", session="s2"),
       s("offer 什么时候到？", session="s3")],
      recall_contains=["字节跳动:offer"]),

    c("M06", "多跳召回", "问投递召回三家公司",
      [s("我投了腾讯和阿里"), s("我投了字节", session="s1b"),
       s("我投过哪些公司？", session="s2")],
      recall_min=3),

    c("M07", "多跳召回", "问名字跨会话召回",
      [s("我叫李雷，我想投后端岗"), s("我叫什么名字？", session="s2")],
      recall_top="李雷", recall_contains=["李雷"]),

    c("M08", "多跳召回", "问城市召回期望城市",
      [s("我想去杭州工作"), s("我想去哪个城市？", session="s2")],
      recall_top="杭州"),

    c("M09", "多跳召回", "问在职公司召回 works_at",
      [s("我现在在美团工作"), s("我现在在哪家公司上班？", session="s2")],
      recall_top="美团"),

    c("M10", "多跳召回", "多轮穿插后仍召回姓名",
      [s("我叫王芳，我投了腾讯"), s("我熟悉 Python", session="s2"),
       s("我叫什么名字？", session="s3")],
      recall_top="王芳"),

    c("M11", "多跳召回", "挂掉后检索只见 ended 不见 interviewing",
      [s("收到字节的面试邀请"), s("字节挂了", session="s2"),
       s("字节的近况？", session="s3")],
      recall_contains=["字节跳动:ended"], recall_not_contains=["interviewing"]),

    c("M12", "多跳召回", "撤回后投递记忆不再被召回",
      [s("我投了阿里巴巴"), s("取消阿里的申请", session="s2"),
       s("我投过哪些公司？", session="s3")],
      recall_not_contains=["阿里巴巴"]),

    c("M13", "多跳召回", "流程结束后历史仍可召回",
      [s("我投了字节跳动"), s("字节流程结束了", session="s2"),
       s("我投过哪些公司？", session="s3")],
      recall_contains=["字节跳动"]),

    c("M14", "多跳召回", "技能更新后问技能召回新旧两条",
      [s("我熟悉 Python"), s("我掌握 Rust", session="s2"),
       s("我会什么技能？", session="s3")],
      recall_min=2, recall_contains=["Python", "Rust"]),

    c("M15", "多跳召回", "岗位更替后召回只出新岗位",
      [s("我想投后端岗"), s("改投 Agent 岗了", session="s2"),
       s("我的目标岗位是什么？", session="s3")],
      recall_top="Agent岗", recall_not_contains=["后端岗"]),

    c("M16", "多跳召回", "城市更替后召回只出新城市",
      [s("我想去北京工作"), s("我想去杭州工作", session="s2"),
       s("我想去哪个城市发展？", session="s3")],
      recall_top="杭州", recall_not_contains=["北京"]),

    c("M17", "多跳召回", "三类记忆并存时问名字精确命中",
      [s("我叫李雷"), s("我熟悉 Python", session="s1b"), s("我投了字节跳动", session="s1c"),
       s("我叫什么名字？", session="s2")],
      recall_top="李雷", recall_min=1),

    c("M18", "多跳召回", "查询同时提到两家公司",
      [s("我投了字节跳动"), s("我投了美团", session="s1b"),
       s("字节和美团哪家先给消息？", session="s2")],
      recall_min=2),

    c("M19", "多跳召回", "提公司名带出在职+投递+状态三条",
      [s("我现在在字节工作"), s("我投了字节跳动", session="s1b"),
       s("在字节工作感觉怎么样？", session="s2")],
      recall_min=2, recall_contains=["字节跳动"]),

    c("M20", "多跳召回", "全链路：自我介绍+投递+改岗后问姓名",
      [s("我叫王芳，我想投 Agent 岗"), s("我投了字节跳动", session="s1b"),
       s("改投后端岗了", session="s1c"), s("我叫什么名字？", session="s2")],
      recall_top="王芳",
      count_active_pred={"name": 1, "target_role": 1, "applied_to": 1}),
]


def main() -> None:
    assert len(CASES) == 100, f"用例数 {len(CASES)} != 100"
    sids = [x["sid"] for x in CASES]
    assert len(set(sids)) == 100, "sid 重复"
    layers: dict[str, int] = {}
    for x in CASES:
        layers[x["layer"]] = layers.get(x["layer"], 0) + 1
    assert all(v == 20 for v in layers.values()), layers
    out = Path(__file__).resolve().parent / "eval_set_100.json"
    out.write_text(json.dumps(CASES, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"eval_set_100.json 已生成：{len(CASES)} 条，分层 {layers}")


if __name__ == "__main__":
    sys.exit(main())
