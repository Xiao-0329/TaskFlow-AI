"""分配引擎（Phase 1：建议 + 人工确认）。

不做全自动分配——信任建立前，系统只给出推荐排序，管理者一键确认。
推荐逻辑：技能匹配 > 能力与难度匹配（70% 成功率原则）> 负载均衡。
"""
from sqlalchemy.orm import Session

from .. import models
from .evaluate import suggest_difficulty_cap


def recommend_for_task(db: Session, task: models.Task) -> list[dict]:
    """为单个任务推荐候选员工（降序），含推荐理由。"""
    employees = db.query(models.Employee).filter(models.Employee.on_leave.is_(False)).all()
    task_skills = {s.lower() for s in (task.skill_tags or [])}

    scored = []
    for e in employees:
        reasons = []
        emp_skills = {s.lower() for s in (e.skills or [])}
        skill_overlap = len(task_skills & emp_skills)

        # 1) 技能匹配（权重最高）
        skill_score = skill_overlap * 30 if task_skills else 15
        if skill_overlap:
            reasons.append(f"技能匹配 {skill_overlap} 项")

        # 2) 难度与能力匹配：难度略低于能力对应档位最优（70% 成功率）
        cap = suggest_difficulty_cap(e.capability)
        if task.difficulty <= cap:
            fit = 30 - (cap - task.difficulty) * 6  # 刚好在能力边缘时最优
            reasons.append(f"难度匹配（能力建议上限 D{cap}）")
        else:
            fit = -(task.difficulty - cap) * 15  # 超出能力档位强惩罚
            reasons.append(f"难度超出建议档位（D{cap}）")

        # 3) 负载均衡：当前未完成任务越多越不推荐
        load = e.current_load
        load_score = -load * 12
        if load >= 3:
            reasons.append(f"负载过高（{load} 个未完成任务）")
        elif load == 0:
            reasons.append("当前无负载")

        total = skill_score + fit + load_score
        scored.append({
            "employee_id": e.id,
            "employee_name": e.name,
            "role": e.role,
            "capability": e.capability,
            "current_load": load,
            "score": total,
            "reasons": reasons,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
