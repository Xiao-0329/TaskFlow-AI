"""拆解与评估的 prompt 模板 + JSON Schema（用于 ollama 结构化输出）。"""

# TDL 拆解输出的 JSON Schema（ollama format 用，语法约束解码）
TDL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "拆解思路简述"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "deliverable_type": {"type": "string", "enum": ["code", "document", "data", "image"]},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                    "skill_tags": {"type": "array", "items": {"type": "string"}},
                    "est_hours": {"type": "number"},
                    "difficulty": {"type": "integer"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                },
                "required": ["title", "description", "deliverable_type", "acceptance",
                             "skill_tags", "est_hours", "difficulty", "depends_on", "priority"],
            },
        },
    },
    "required": ["summary", "tasks"],
}

# 里程碑规划的 JSON Schema
MILESTONE_SCHEMA = {
    "type": "object",
    "properties": {
        "milestones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "goal": {"type": "string"},
                    "scope_hint": {"type": "string"},
                    "est_days": {"type": "integer"},
                },
                "required": ["title", "goal", "scope_hint", "est_days"],
            },
        },
    },
    "required": ["milestones"],
}

# 评估输出的 JSON Schema
EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "quality_score": {"type": "integer"},
        "efficiency_score": {"type": "integer"},
        "feedback": {"type": "string"},
    },
    "required": ["quality_score", "efficiency_score", "feedback"],
}


MILESTONE_SYSTEM = """你是一位资深的项目管理专家（PMP），擅长为项目制定里程碑计划。

你必须输出严格的 JSON，不要输出任何其他文字。输出结构：
{
  "milestones": [
    {
      "title": "阶段名（10字内）",
      "goal": "该阶段要达成的目标",
      "scope_hint": "范围与要点提示（给后续任务拆解用）",
      "est_days": 5
    }
  ]
}

规划原则：
1. 按交付节奏把项目切成 2-6 个阶段，每个阶段 3-10 个工作日
2. 阶段之间有清晰的交付物边界（一个阶段结束应该有可验收的产出）
3. est_days 是该阶段全部任务的总工作日数（团队合计）
4. 阶段顺序符合依赖逻辑"""


def milestone_user(project_name: str, goal: str, description: str, industry_hint: str = "") -> str:
    return f"""请为以下项目制定里程碑阶段计划。

【项目名称】{project_name}
【项目目的】{goal or '（未提供）'}
【项目描述】{description or '（未提供）'}
【行业特性】{industry_hint or '（未指定行业）'}"""


PHASE_DECOMPOSE_SYSTEM = """你是一位资深的项目管理专家（PMP），擅长把一个项目阶段拆解为员工一天内可完成的原子任务。

你必须输出严格的 JSON，不要输出任何其他文字。输出结构：
{
  "summary": "拆解思路简述（50字内）",
  "tasks": [
    {
      "title": "任务标题（一句话，20字内）",
      "description": "任务说明：上下文、范围、注意事项",
      "deliverable_type": "code|document|data|image 之一",
      "acceptance": ["验收标准1", "验收标准2"],
      "skill_tags": ["所需技能标签"],
      "est_hours": 6,
      "difficulty": 3,
      "depends_on": ["依赖的前置任务标题，无则空数组"],
      "priority": "P1"
    }
  ]
}

拆解原则：
1. 只拆解指定的这一个阶段，不要拆其他阶段的内容
2. 每个任务必须一天内可完成（est_hours 在 2-8 小时之间）
3. 任务数量 = 阶段总人日数 ÷ 团队可投入人数，通常 5-12 个
4. 每个任务必须有明确、可验证的交付物和验收标准
5. 任务之间的依赖关系要明确（depends_on 引用其他任务的标题）
6. 难度 1-5 分布要有梯度，便于分配给不同能力的员工
7. 优先级：P0 最紧急，P3 最不紧急"""


def phase_decompose_user(
    project_name: str, goal: str, milestone: dict, team_context: str, done_context: str,
    industry_hint: str = "",
) -> str:
    return f"""请把以下项目阶段拆解为天级任务。

【项目名称】{project_name}
【项目目的】{goal or '（未提供）'}
【行业特性】{industry_hint or '（未指定行业）'}
【要拆解的阶段】{milestone['title']}
【阶段目标】{milestone['goal']}
【阶段范围提示】{milestone.get('scope_hint', '')}
【阶段预估工作日】{milestone.get('est_days', 5)} 人日
【团队情况】{team_context or '（未提供）'}
【已完成的前序阶段任务】{done_context or '（无，这是第一个阶段）'}"""


def decompose_user(project_name: str, goal: str, description: str, team_context: str) -> str:
    return f"""请拆解以下项目为天级任务。

【项目名称】{project_name}
【项目目的】{goal or '（未提供）'}
【项目描述】{description or '（未提供）'}
【团队情况】{team_context or '（未提供）'}"""


EVALUATE_SYSTEM = """你是一位严格但公正的工作质量评审专家。你的任务是评估员工提交的任务交付物。

你必须输出严格的 JSON，不要输出任何其他文字。输出结构：
{
  "quality_score": 0-100 的整数,
  "efficiency_score": 0-100 的整数,
  "feedback": "评估反馈，必须具体：哪条验收标准达成/未达成、好在哪、差在哪、下次怎么改进"
}

评分规则：
- quality_score：逐条对照任务的验收标准（acceptance）和交付物要求评分。全部达成且质量高=90+；基本达成=70-89；部分达成=50-69；未达成或敷衍=<50
- efficiency_score：结合预估工时与员工自报耗时评估。提前且质量达标=90+；按期=70-89；超时=<70（若质量极高可适当上调）
- feedback 必须可解释、可执行，不能只说"做得不错"
- 提交内容明显敷衍（如内容过短、答非所问）时大幅扣分并明确指出"""


def evaluate_user(
    task_json: str, submission_content: str, spent_hours: float, est_hours: float,
    industry_hint: str = "",
) -> str:
    return f"""请评估以下任务提交。

【任务 TDL】
{task_json}

【行业评分侧重】{industry_hint or '（未指定行业）'}

【预估工时】{est_hours} 小时
【员工自报实际耗时】{spent_hours} 小时

【员工提交的交付物内容如下：】
{submission_content or '（空白提交）'}"""
