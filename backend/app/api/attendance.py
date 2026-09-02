"""考勤 API：打卡事件（员工）+ 考勤/排班视图（管理员）。

打卡通道（source）：
  manual  —— 本系统打卡按钮（当前实现）
  dingtalk / wecom / feishu —— 预留适配位（需企业自建应用凭证，Phase 2 接入）
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..db import get_db
from ..services import dispatch, schedule

router = APIRouter(prefix="/api", tags=["attendance"])


def _today_records(db: Session, employee_id: int) -> list[models.AttendanceRecord]:
    return (
        db.query(models.AttendanceRecord)
        .filter(
            models.AttendanceRecord.employee_id == employee_id,
            models.AttendanceRecord.created_at >= datetime.combine(date.today(), datetime.min.time()),
        )
        .order_by(models.AttendanceRecord.created_at)
        .all()
    )


class ClockOut(BaseModel):
    source: str = "manual"


# ================================================================ 员工：上班打卡
@router.post("/me/clock-in")
def clock_in(
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上班打卡：记录考勤 + 自动派发当日任务。

    休息日打卡给出提醒（不阻止——加班场景）。
    """
    if not schedule.is_on_duty(user):
        on_duty_note = "今天不在你的排班日内（加班辛苦了）"
    else:
        on_duty_note = None

    rec = models.AttendanceRecord(employee_id=user.id, type="in", source="manual")
    db.add(rec)
    db.commit()

    new_tasks = dispatch.auto_dispatch(db, user)

    return {
        "ok": True,
        "on_duty_note": on_duty_note,
        "dispatched": [
            {"id": t.id, "title": t.title, "est_hours": t.est_hours, "difficulty": t.difficulty}
            for t in new_tasks
        ],
        "dispatch_note": f"已自动领取 {len(new_tasks)} 个任务（按优先级、能力上限、依赖关系筛选）"
        if new_tasks else "任务池中没有适合你的任务（可能已被领取完或依赖未满足）",
    }


# ================================================================ 员工：下班打卡
@router.post("/me/clock-out")
def clock_out(
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下班打卡：记录考勤 + 当日汇总（未提交任务会提醒）。"""
    rec = models.AttendanceRecord(employee_id=user.id, type="out", source="manual")
    db.add(rec)
    db.commit()

    summary = dispatch.daily_summary(db, user)
    summary["ok"] = True
    if summary["unsubmitted"]:
        summary["warning"] = f"有 {len(summary['unsubmitted'])} 个任务未提交：{'；'.join(summary['unsubmitted'])}"
    return summary


# ================================================================ 员工：今日打卡状态
@router.get("/me/attendance")
def my_attendance_today(
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = _today_records(db, user.id)
    return {
        "clock_in": next((r.created_at.isoformat() for r in records if r.type == "in"), None),
        "clock_out": next((r.created_at.isoformat() for r in records if r.type == "out"), None),
        "on_duty_today": schedule.is_on_duty(user),
        "work_pattern": user.work_pattern,
    }


# ================================================================ 管理员：考勤与排班视图
@router.get("/attendance/today")
def attendance_today(user: models.Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    # 权限：非管理员只能看自己
    employees = db.query(models.Employee).all()
    result = []
    for e in employees:
        if not user.is_admin and e.id != user.id:
            continue
        records = _today_records(db, e.id)
        result.append({
            "employee_id": e.id, "name": e.name, "role": e.role,
            "work_pattern": e.work_pattern, "on_duty": schedule.is_on_duty(e),
            "clock_in": next((r.created_at.isoformat() for r in records if r.type == "in"), None),
            "clock_out": next((r.created_at.isoformat() for r in records if r.type == "out"), None),
        })
    return result


@router.get("/schedule")
def schedule_view(
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """排班日历：管理员看全员，员工看自己。"""
    employees = db.query(models.Employee).all()
    result = []
    for e in employees:
        if not user.is_admin and e.id != user.id:
            continue
        result.append({
            "employee_id": e.id, "name": e.name, "role": e.role,
            "work_pattern": e.work_pattern,
            "anchor": e.schedule_anchor.isoformat() if e.schedule_anchor else None,
            "on_duty_today": schedule.is_on_duty(e),
            "calendar": schedule.calendar(e, days=14),
        })
    return result


class PatternIn(BaseModel):
    pattern: str  # standard | 2on2off
    anchor: str | None = None  # YYYY-MM-DD，2on2off 的周期起点


@router.post("/employees/{employee_id}/pattern")
def set_pattern(
    employee_id: int,
    data: PatternIn,
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """设置排班模式（管理员）。"""
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    e = db.get(models.Employee, employee_id)
    if not e:
        raise HTTPException(404, "员工不存在")
    try:
        anchor = date.fromisoformat(data.anchor) if data.anchor else date.today()
        schedule.apply_pattern(e, data.pattern, anchor)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    db.commit()
    return {"ok": True, "pattern": e.work_pattern}
