"""TDL（Task Definition Language）—— 任务定义语言。

整个系统的数据契约：LLM 拆解的输出、分配引擎的输入、评估引擎的依据，全部围绕 TDL。
每个任务 = 交付物 + 技能标签 + 预估工时 + 依赖 + 验收标准。
"""
from pydantic import BaseModel, Field, field_validator


DELIVERABLE_TYPES = ("code", "document", "data", "image")


class TDLSchema(BaseModel):
    """单个天级任务的 TDL 结构。"""

    title: str = Field(..., max_length=200, description="任务标题，一句话说清做什么")
    description: str = Field(default="", description="任务说明：上下文、范围、注意事项")
    deliverable_type: str = Field(default="document", description="交付物类型: code|document|data|image")
    acceptance: list[str] = Field(default_factory=list, description="验收标准，逐条可勾选")
    skill_tags: list[str] = Field(default_factory=list, description="完成此任务所需技能标签")
    est_hours: float = Field(default=6.0, ge=0.5, le=16, description="预估工时（小时），一天内可完成")
    difficulty: int = Field(default=3, ge=1, le=5, description="难度 1-5")
    depends_on: list[str] = Field(default_factory=list, description="依赖的前置任务标题")
    priority: str = Field(default="P2", description="优先级 P0-P3")
    due_date: str | None = Field(default=None, description="截止日期 YYYY-MM-DD，可选")

    @field_validator("deliverable_type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in DELIVERABLE_TYPES:
            raise ValueError(f"deliverable_type 必须是 {DELIVERABLE_TYPES} 之一")
        return v

    @field_validator("priority")
    @classmethod
    def check_priority(cls, v: str) -> str:
        v = v.upper()
        if v not in ("P0", "P1", "P2", "P3"):
            raise ValueError("priority 必须是 P0-P3")
        return v

    @field_validator("title")
    @classmethod
    def check_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title 不能为空")
        return v


class TDLLLMOutput(BaseModel):
    """LLM 拆解的完整输出：任务列表 + 拆解说明。"""

    tasks: list[TDLSchema]
    summary: str = Field(default="", description="拆解思路简述")


def validate_llm_tasks(raw: dict | list) -> TDLLLMOutput:
    """校验并规范化 LLM 输出的任务列表。

    容错策略：单条任务非法时丢弃该条而不是整体失败（LLM 输出不可全信）。
    """
    if isinstance(raw, dict):
        tasks_raw = raw.get("tasks", raw.get("task_list", []))
        summary = raw.get("summary", "")
    else:
        tasks_raw, summary = raw, ""

    valid, errors = [], []
    for i, item in enumerate(tasks_raw):
        try:
            if not isinstance(item, dict):
                raise ValueError("任务必须是对象")
            # 依赖字段容错：LLM 可能输出 dependsOn / depends
            if "depends_on" not in item:
                item["depends_on"] = item.pop("dependsOn", item.pop("depends", []))
            if "est_hours" not in item and "estHours" in item:
                item["est_hours"] = item["estHours"]
            valid.append(TDLSchema(**item))
        except Exception as e:
            errors.append(f"任务 #{i + 1}: {e}")
    if not valid:
        raise ValueError(f"LLM 未产出任何合法任务。错误: {errors}")
    return TDLLLMOutput(tasks=valid, summary=summary)
