"""自动派发引擎：员工上班打卡后，按约束自动从任务池领取当日任务。

派发规则（按序过滤）：
  1. 任务池中已审核、未分配的任务
  2. 依赖满足：depends_on 引用的任务（同项目按标题匹配）已全部完成
  3. 难度不超员工能力上限（难度爬坡）
  4. 技能匹配：员工技能与任务技能标签有交集（任务无技能要求则直接通过）
  5. 按优先级排序，逐个领取直到当日工时容量满
"""
from datetime import date

from sqlalchemy.orm import Session

from .. import models
from ..industry import get_pack
from .evaluate import suggest_difficulty_cap
from .schedule import DAILY_CAPACITY_HOURS

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _deps_satisfied(db: Session, task: models.Task) -> bool:
    """依赖检查：depends_on 存的是前置任务标题，在同项目内按标题找已完成任务。"""
    if not task.depends_on:
        return True
    for title in task.depends_on:
        dep = (
            db.query(models.Task)
            .filter(
                models.Task.project_id == task.project_id,
                models.Task.title == title,
                models.Task.status == "reviewed",
            )
            .first()
        )
        if not dep:
            return False
    return True


def auto_dispatch(db: Session, employee: models.Employee) -> list[models.Task]:
    """上班打卡后自动派发当日任务。返回本次新分配的任务列表。

    行业包影响容量：响应型（客服/运维/护理）只排 60% 工时，预留事件处理容量。
    """
    if employee.on_leave:
        return []

    cap = suggest_difficulty_cap(employee.capability)
    emp_skills = {s.lower() for s in (employee.skills or [])}

    pool = (
        db.query(models.Task)
        .filter(models.Task.review_status == "approved", models.Task.status == "pending")
        .all()
    )

    # 已有进行中的任务也计入当日容量
    current = (
        db.query(models.Task)
        .filter(models.Task.assigned_employee_id == employee.id,
                models.Task.status.in_(("assigned", "submitted")))
        .all()
    )
    load_hours = sum(t.est_hours for t in current)

    candidates = []
    for t in pool:
        if t.difficulty > cap:
            continue
        if not _deps_satisfied(db, t):
            continue
        task_skills = {s.lower() for s in (t.skill_tags or [])}
        if task_skills and not (task_skills & emp_skills):
            continue
        candidates.append(t)

    candidates.sort(key=lambda t: (PRIORITY_ORDER.get(t.priority, 9), -t.difficulty))

    assigned = []
    for t in candidates:
        # 按任务所属项目的行业包计算有效容量（响应型预留 40% 应急）
        task_capacity = DAILY_CAPACITY_HOURS * get_pack(t.project.industry).dispatch_capacity_ratio
        if load_hours + t.est_hours > task_capacity:
            continue
        t.assigned_employee_id = employee.id
        t.status = "assigned"
        assigned.append(t)
        load_hours += t.est_hours
        if load_hours >= DAILY_CAPACITY_HOURS:
            break

    if assigned:
        db.commit()
    return assigned


def daily_summary(db: Session, employee: models.Employee) -> dict:
    """下班打卡时的当日汇总（看当天处于进行中/已提交/已完成的任务）。"""
    tasks = (
        db.query(models.Task)
        .filter(
            models.Task.assigned_employee_id == employee.id,
            models.Task.status.in_(("assigned", "submitted", "reviewed")),
        )
        .all()
    )
    today = date.today()
    todays = [t for t in tasks if t.due_date == today] or tasks

    unsubmitted = [t.title for t in todays if t.status == "assigned"]
    submitted = [t for t in todays if t.status in ("submitted", "reviewed")]

    scores = [
        s.evaluation.total_score
        for t in submitted
        for s in t.submissions
        if s.evaluation and s.submitted_at.date() == today
    ]

    return {
        "assigned_count": len(todays),
        "submitted_count": len(submitted),
        "unsubmitted": unsubmitted,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "total_hours": round(sum(t.est_hours for t in todays), 1),
    }
