"""全局调度器：跨项目的负载统筹。

职责：
  1. 僵尸任务回收 —— 分配超时未提交的任务自动回收（释放容量），员工端有记录可查
  2. 多项目全局排序 —— 项目紧急度（deadline 临近度）+ 任务优先级 + 难度
  3. 负载统计 —— 每员工跨项目总工时/容量利用率/逾期数，给管理员全局视图
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from .schedule import DAILY_CAPACITY_HOURS

# 分配后 N 天未提交视为僵尸任务（天级任务的本意就是当天完成，宽限到 2 天）
ZOMBIE_DAYS = 2

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


# ================================================================ 僵尸任务回收
def recycle_stale_tasks(db: Session, before_dispatch: bool = True) -> list[models.Task]:
    """回收超时未提交的任务：status 回 pending、清空分配人、记回收原因。

    触发时机：auto_dispatch 之前（before_dispatch=True）或管理员手动调用。
    回收的任务出现在全局任务池，可被任何人（含原员工）重新领取。
    """
    cutoff = datetime.now() - timedelta(days=ZOMBIE_DAYS)
    zombies = (
        db.query(models.Task)
        .filter(
            models.Task.status == "assigned",
            models.Task.assigned_at.isnot(None),
            models.Task.assigned_at < cutoff,
        )
        .all()
    )
    for t in zombies:
        t.status = "pending"
        t.assigned_employee_id = None
        t.assigned_at = None
        # 回收记录写在 description 尾部，员工/管理员可见（MVP 级通知方案）
        note = f"\n[系统] 该任务曾于 {cutoff.date()} 因超时未提交被自动回收重新入池。"
        if "[系统] 该任务曾于" not in t.description:
            t.description = (t.description or "") + note
    if zombies:
        db.commit()
    return zombies


# ================================================================ 多项目全局排序
def _project_urgency(project: models.Project, today: date | None = None) -> float:
    """项目紧急度 0-100：deadline 越近越紧急；无 deadline 为中位 50。"""
    today = today or date.today()
    if not project.deadline:
        return 50.0
    days_left = (project.deadline - today).days
    if days_left <= 0:
        return 100.0   # 已逾期，最高紧急
    if days_left >= 30:
        return 10.0
    # 30 天内线性映射：30天→10，0天→100
    return round(10.0 + (30 - days_left) * 90.0 / 30, 1)


def global_sort_key(task: models.Task) -> tuple:
    """全局排序键：(项目紧急度降序, 任务优先级, 难度降序)。"""
    return (
        -_project_urgency(task.project),
        PRIORITY_ORDER.get(task.priority, 9),
        -task.difficulty,
    )


# ================================================================ 负载统计
def employee_loads(db: Session) -> list[dict]:
    """全员跨项目负载统计（管理员仪表盘）。"""
    today = date.today()
    employees = db.query(models.Employee).filter(models.Employee.is_admin.is_(False)).all()
    tasks = (
        db.query(models.Task)
        .filter(models.Task.assigned_employee_id.isnot(None),
                models.Task.status.in_(("assigned", "submitted")))
        .all()
    )
    result = []
    for e in employees:
        mine = [t for t in tasks if t.assigned_employee_id == e.id]
        load_hours = sum(t.est_hours for t in mine)
        # 有效容量按员工最常接的行业（此处取全部在途任务中行业包最小容量，保守估计）
        ratios = {DAILY_CAPACITY_HOURS * _ratio_for(t) for t in mine}
        capacity = min(ratios) if ratios else DAILY_CAPACITY_HOURS
        overdue = [t for t in mine if t.due_date and t.due_date < today]
        result.append({
            "employee_id": e.id,
            "name": e.name,
            "role": e.role,
            "on_leave": e.on_leave,
            "capability": e.capability,
            "load_hours": round(load_hours, 1),
            "capacity": capacity,
            "utilization": round(load_hours / capacity * 100) if capacity else 0,
            "active_tasks": len(mine),
            "overdue_count": len(overdue),
            "projects": sorted({t.project.name for t in mine}),
        })
    # 超载的排前面
    result.sort(key=lambda r: -r["utilization"])
    return result


def _ratio_for(task: models.Task) -> float:
    from ..industry import get_pack
    return get_pack(task.project.industry).dispatch_capacity_ratio


def overview(db: Session) -> dict:
    """管理员总览仪表盘数据：负载 + 任务池 + 项目紧急度 + 回收建议。"""
    today = date.today()

    # 负载
    loads = employee_loads(db)

    # 任务池（全局排序）
    pool = (
        db.query(models.Task)
        .filter(models.Task.review_status == "approved", models.Task.status == "pending")
        .all()
    )
    pool_sorted = sorted(pool, key=global_sort_key)
    pool_out = [
        {
            "id": t.id, "title": t.title, "project": t.project.name,
            "project_deadline": t.project.deadline.isoformat() if t.project.deadline else None,
            "urgency": _project_urgency(t.project, today),
            "priority": t.priority, "difficulty": t.difficulty,
            "est_hours": t.est_hours, "phase": t.phase,
        }
        for t in pool_sorted
    ]

    # 项目紧急度
    projects = db.query(models.Project).filter(models.Project.status == "active").all()
    proj_out = sorted(
        (
            {
                "id": p.id, "name": p.name, "deadline": p.deadline.isoformat() if p.deadline else None,
                "urgency": _project_urgency(p, today),
                "pending": sum(1 for t in p.tasks if t.status == "pending" and t.review_status == "approved"),
                "done": sum(1 for t in p.tasks if t.status == "reviewed"),
            }
            for p in projects
        ),
        key=lambda x: -x["urgency"],
    )

    # 僵尸任务预警（不自动回收，列出给管理员决策）
    cutoff = datetime.now() - timedelta(days=ZOMBIE_DAYS)
    stale = (
        db.query(models.Task)
        .filter(
            models.Task.status == "assigned",
            models.Task.assigned_at.isnot(None),
            models.Task.assigned_at < cutoff,
        )
        .all()
    )
    stale_out = [
        {
            "id": t.id, "title": t.title, "assigned_to": t.assigned_employee.name if t.assigned_employee else None,
            "assigned_at": t.assigned_at.isoformat(), "est_hours": t.est_hours,
        }
        for t in stale
    ]

    return {
        "loads": loads,
        "pool": pool_out,
        "projects": proj_out,
        "stale_tasks": stale_out,
        "today": today.isoformat(),
    }
