"""行业包（Industry Pack）：让不同行业的公司按自家业务调整系统行为。

一个行业包 = 拆解提示 + 评估权重/侧重点 + 派发容量策略。

MVP 内置三套；后续可开放为 DB 配置让企业自定义（FDE 交付的配置面）。
"""
from pydantic import BaseModel, Field


class IndustryPack(BaseModel):
    key: str
    name: str
    description: str
    # 拆解注入：行业任务模式与拆解注意事项（进入里程碑+阶段拆解 prompt）
    decompose_hint: str = ""
    # 评估注入：行业评分侧重点（进入评估 prompt）
    eval_hint: str = ""
    # 评估权重：质量/效率
    quality_weight: float = Field(default=0.7, ge=0, le=1)
    efficiency_weight: float = Field(default=0.3, ge=0, le=1)
    # 派发容量比：1.0=排满工时；<1 为响应型预留事件处理容量
    dispatch_capacity_ratio: float = Field(default=1.0, gt=0, le=1)
    # 该行业常见技能标签（录入员工时参考）
    suggested_skills: list[str] = []


KNOWLEDGE = IndustryPack(
    key="knowledge",
    name="知识型（软件/咨询/设计）",
    description="脑力产出为主，交付物多为文档/代码/数据，按计划推进",
    decompose_hint=(
        "本行业为知识型工作：任务以脑力产出为主，交付物多为文档、代码、数据。"
        "参考任务节奏：调研→设计→实现→测试→交付。"
        "任务应强调交付物的可验收性（文档结构完整、代码可运行、数据可核对）。"
    ),
    eval_hint="重点关注：交付物完整性与可维护性、与验收标准的逐条匹配度、文档/代码质量。",
    quality_weight=0.7,
    efficiency_weight=0.3,
    dispatch_capacity_ratio=1.0,
    suggested_skills=["调研", "设计", "开发", "测试", "文档", "数据分析"],
)

PRODUCTION = IndustryPack(
    key="production",
    name="生产型（制造/工程/施工）",
    description="现场作业为主，受设备产能、物料、安全规范约束",
    decompose_hint=(
        "本行业为生产型工作：任务以现场作业为主（备料、加工、装配、质检、巡检、维保）。"
        "拆解时注意：任务受设备产能和物料齐套约束，需要前置检查项；"
        "每类作业任务的验收标准必须包含安全合规项（SOP/劳保/危险源确认）。"
    ),
    eval_hint=(
        "重点关注：良率与返工率、SOP 遵循度、安全合规。"
        "出现安全违规或漏检属于严重问题，应大幅扣分（低于 40 分）。"
    ),
    quality_weight=0.8,
    efficiency_weight=0.2,
    dispatch_capacity_ratio=1.0,
    suggested_skills=["操作", "质检", "维保", "安全", "排产", "工艺"],
)

RESPONSE = IndustryPack(
    key="response",
    name="响应型（客服/运维/护理）",
    description="事件驱动，按班次值守，不可预拆的工单随时插入",
    decompose_hint=(
        "本行业为响应型工作：任务以事件响应为主（值守、工单处理、巡检监测、应急处理）。"
        "拆解时注意：常规任务只占员工部分工时，必须预留事件响应容量——"
        "每个员工每日的常规任务工时合计不超过 5 小时，其余时间应对突发工单。"
        "任务按班次组织，交接班记录可作为交付物。"
    ),
    eval_hint=(
        "重点关注：响应时效（是否超时）、一次解决率、服务规范与记录完整性。"
        "工单积压、超时未响应是重要扣分项；交接记录缺失应扣分。"
    ),
    quality_weight=0.6,
    efficiency_weight=0.4,
    dispatch_capacity_ratio=0.6,
    suggested_skills=["值守", "工单", "沟通", "应急", "记录"],
)

PACKS: dict[str, IndustryPack] = {p.key: p for p in (KNOWLEDGE, PRODUCTION, RESPONSE)}


def get_pack(key: str | None) -> IndustryPack:
    """按 key 取行业包；未知/未设置回退到知识型。"""
    return PACKS.get(key or "knowledge", KNOWLEDGE)


def list_packs() -> list[dict]:
    return [
        {
            "key": p.key, "name": p.name, "description": p.description,
            "quality_weight": p.quality_weight,
            "efficiency_weight": p.efficiency_weight,
            "dispatch_capacity_ratio": p.dispatch_capacity_ratio,
            "suggested_skills": p.suggested_skills,
        }
        for p in PACKS.values()
    ]
