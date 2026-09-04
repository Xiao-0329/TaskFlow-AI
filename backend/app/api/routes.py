"""API 路由。

三个 router 按角色划分：
  public  登录（无需 token）
  admin   全部管理功能（员工/项目/拆解/审核/分配/评估）
  me      员工自助（我的任务、提交交付物、我的记录、请假）
"""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..auth import admin_required, get_current_user, hash_password, make_token
from ..db import get_db
from ..industry import get_pack, list_packs
from ..llm import gateway
from ..services import decompose, evaluate, assign
from . import webhooks

public = APIRouter(prefix="/api")
admin = APIRouter(prefix="/api", dependencies=[Depends(admin_required)])
me = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


# ================================================================ 登录
class LoginIn(BaseModel):
    username: str
    password: str


@public.post("/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    """登录：username 支持用户名或姓名，返回角色化 token。"""
    emp = (
        db.query(models.Employee)
        .filter((models.Employee.username == data.username) | (models.Employee.name == data.username))
        .first()
    )
    if not emp or not emp.password_hash or emp.password_hash != hash_password(data.password):
        raise HTTPException(401, "用户名或密码错误")
    return {
        "token": make_token(emp.id),
        "employee_id": emp.id,
        "name": emp.name,
        "role": "admin" if emp.is_admin else "employee",
    }


@public.get("/llm-info")
def llm_info():
    return gateway.provider_info()


@public.get("/industries")
def industries():
    """行业包列表（登录页/项目表单用，公开只读）。"""
    return list_packs()


# ================================================================ 员工管理（管理员）
class EmployeeIn(BaseModel):
    name: str
    role: str = ""
    skills: list[str] = []
    on_leave: bool = False
    username: str = ""
    password: str = "123456"  # 默认密码，管理员创建员工时可不填


@admin.get("/employees")
def list_employees(db: Session = Depends(get_db)):
    return [
        {
            "id": e.id, "name": e.name, "role": e.role, "skills": e.skills,
            "capability": e.capability, "task_count": e.task_count,
            "current_load": e.current_load, "on_leave": e.on_leave,
            "username": e.username,
            "external_ids": e.external_ids or {},
            "difficulty_cap": evaluate.suggest_difficulty_cap(e.capability),
        }
        for e in db.query(models.Employee).filter(models.Employee.is_admin.is_(False)).all()
    ]


@admin.put("/employees/{employee_id}/external-id")
def set_external_id(employee_id: int, data: webhooks.ExternalIdIn, db: Session = Depends(get_db)):
    """绑定员工的外部考勤账号（飞书/钉钉/企微 userId），供 webhook 事件匹配。"""
    return webhooks.bind_external_id(db, employee_id, data.platform, data.external_id)


@admin.post("/employees")
def create_employee(data: EmployeeIn, db: Session = Depends(get_db)):
    username = (data.username or data.name).strip()
    if db.query(models.Employee).filter(models.Employee.username == username).first():
        raise HTTPException(400, f"用户名 {username} 已存在")
    e = models.Employee(
        name=data.name, role=data.role, skills=data.skills, on_leave=data.on_leave,
        username=username, password_hash=hash_password(data.password), is_admin=False,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return {"id": e.id, "username": e.username}


@admin.put("/employees/{employee_id}")
def update_employee(employee_id: int, data: EmployeeIn, db: Session = Depends(get_db)):
    e = db.get(models.Employee, employee_id)
    if not e:
        raise HTTPException(404, "员工不存在")
    e.name, e.role, e.skills, e.on_leave = data.name, data.role, data.skills, data.on_leave
    if data.password:
        e.password_hash = hash_password(data.password)
    if data.username and data.username != e.username:
        if db.query(models.Employee).filter(models.Employee.username == data.username).first():
            raise HTTPException(400, f"用户名 {data.username} 已存在")
        e.username = data.username
    db.commit()
    return {"ok": True}


@admin.delete("/employees/{employee_id}")
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    e = db.get(models.Employee, employee_id)
    if not e:
        raise HTTPException(404, "员工不存在")
    db.delete(e)
    db.commit()
    return {"ok": True}


# ================================================================ 项目（管理员）
class ProjectIn(BaseModel):
    name: str
    goal: str = ""
    description: str = ""
    industry: str = "knowledge"  # knowledge | production | response


@admin.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    result = []
    for p in db.query(models.Project).order_by(models.Project.id.desc()).all():
        tasks = p.tasks
        result.append({
            "id": p.id, "name": p.name, "goal": p.goal, "description": p.description,
            "status": p.status, "industry": p.industry,
            "industry_name": get_pack(p.industry).name,
            "task_total": len(tasks),
            "task_draft": sum(1 for t in tasks if t.review_status == "draft"),
            "task_pending": sum(1 for t in tasks if t.review_status == "approved" and t.status == "pending"),
            "task_done": sum(1 for t in tasks if t.status == "reviewed"),
            "phases": decompose.phase_progress(p),
            "has_milestones": bool(p.milestones),
        })
    return result


@admin.post("/projects")
def create_project(data: ProjectIn, db: Session = Depends(get_db)):
    if data.industry not in ("knowledge", "production", "response"):
        raise HTTPException(400, "industry 必须是 knowledge / production / response 之一")
    p = models.Project(name=data.name, goal=data.goal, description=data.description, industry=data.industry)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id}


@admin.post("/projects/{project_id}/decompose")
def decompose_project_api(project_id: int, db: Session = Depends(get_db)):
    """LLM 拆解项目：首次=规划里程碑+拆第一阶段；之后走 decompose-next 滚动拆解。"""
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    try:
        tasks = decompose.decompose_project(db, p)
    except gateway.LLMError as e:
        raise HTTPException(502, f"LLM 拆解失败: {e}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    phase = tasks[0].phase if tasks else ""
    return {
        "created": len(tasks),
        "phase": phase,
        "summary": f"已拆解阶段「{phase}」的 {len(tasks)} 个任务，请审核",
    }


@admin.post("/projects/{project_id}/decompose-next")
def decompose_next_api(project_id: int, db: Session = Depends(get_db)):
    """滚动拆解：拆下一个未拆解的阶段（前序阶段任务须全部被领取）。"""
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    try:
        tasks = decompose.decompose_next_phase(db, p)
    except gateway.LLMError as e:
        raise HTTPException(502, f"LLM 拆解失败: {e}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    phase = tasks[0].phase if tasks else ""
    return {
        "created": len(tasks),
        "phase": phase,
        "summary": f"已拆解阶段「{phase}」的 {len(tasks)} 个任务，请审核",
    }


@admin.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ================================================================ 任务（管理员）
class TaskIn(BaseModel):
    title: str
    description: str = ""
    deliverable_type: str = "document"
    acceptance: list[str] = []
    skill_tags: list[str] = []
    est_hours: float = 6.0
    difficulty: int = Field(default=3, ge=1, le=5)
    depends_on: list[str] = []
    priority: str = "P2"
    due_date: str | None = None


def _task_out(t: models.Task) -> dict:
    return {
        "id": t.id, "project_id": t.project_id, "project_name": t.project.name,
        "title": t.title, "description": t.description, "phase": t.phase,
        "deliverable_type": t.deliverable_type, "acceptance": t.acceptance,
        "skill_tags": t.skill_tags, "est_hours": t.est_hours,
        "difficulty": t.difficulty, "depends_on": t.depends_on, "priority": t.priority,
        "review_status": t.review_status, "status": t.status, "due_date": t.due_date,
        "assigned_to": t.assigned_employee.name if t.assigned_employee else None,
        "assigned_to_id": t.assigned_employee_id,
    }


@admin.get("/tasks")
def list_tasks(
    project_id: int | None = None,
    review_status: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.Task)
    if project_id:
        q = q.filter(models.Task.project_id == project_id)
    if review_status:
        q = q.filter(models.Task.review_status == review_status)
    if status:
        q = q.filter(models.Task.status == status)
    return [_task_out(t) for t in q.order_by(models.Task.id).all()]


@admin.put("/tasks/{task_id}")
def update_task(task_id: int, data: TaskIn, db: Session = Depends(get_db)):
    """编辑任务（审核环节的主要操作）。"""
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.status != "pending":
        raise HTTPException(400, "仅未开始的任务可编辑")
    for k, v in data.model_dump().items():
        if k == "due_date":
            v = date.fromisoformat(v) if v else None
        setattr(t, k, v)
    db.commit()
    return {"ok": True}


@admin.post("/tasks/{task_id}/review")
def review_task(task_id: int, action: str, db: Session = Depends(get_db)):
    """审核任务：approve（通过，进入待分配池）/ reject（丢弃）。"""
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.review_status != "draft":
        raise HTTPException(400, "仅草稿任务需要审核")
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action 必须是 approve 或 reject")
    if action == "approve":
        t.review_status = "approved"
        db.commit()
        return {"ok": True, "review_status": "approved"}
    db.delete(t)
    db.commit()
    return {"ok": True, "review_status": "rejected"}


@admin.post("/tasks/bulk-review")
def bulk_review(project_id: int, action: str, db: Session = Depends(get_db)):
    """批量审核：一键通过/丢弃该项目的所有草稿任务。"""
    tasks = db.query(models.Task).filter(
        models.Task.project_id == project_id, models.Task.review_status == "draft"
    ).all()
    if action == "approve":
        for t in tasks:
            t.review_status = "approved"
        db.commit()
        return {"approved": len(tasks)}
    for t in tasks:
        db.delete(t)
    db.commit()
    return {"rejected": len(tasks)}


@admin.get("/tasks/{task_id}/candidates")
def task_candidates(task_id: int, db: Session = Depends(get_db)):
    """分配建议：推荐候选员工及理由。"""
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return assign.recommend_for_task(db, t)


@admin.post("/tasks/{task_id}/assign")
def assign_task(task_id: int, employee_id: int, db: Session = Depends(get_db)):
    """分配任务给员工（Phase 1：管理者确认制）。"""
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.review_status != "approved":
        raise HTTPException(400, "任务未通过审核，不能分配")
    if t.status != "pending":
        raise HTTPException(400, "任务已分配或已完成")
    e = db.get(models.Employee, employee_id)
    if not e or e.is_admin:
        raise HTTPException(404, "员工不存在")
    t.assigned_employee_id = employee_id
    t.status = "assigned"
    db.commit()
    return {"ok": True}


# ================================================================ 提交与评估（管理员查看/触发）
def _evaluation_out(ev: models.Evaluation | None) -> dict | None:
    """评估结果统一序列化（含逐条明细与防作弊标记）。"""
    if not ev:
        return None
    return {
        "quality_score": ev.quality_score,
        "efficiency_score": ev.efficiency_score,
        "total_score": ev.total_score,
        "feedback": ev.feedback,
        "criteria": ev.criterion_scores or [],
        "flags": ev.flags or [],
    }


@admin.get("/submissions")
def list_submissions(db: Session = Depends(get_db)):
    result = []
    for s in db.query(models.Submission).order_by(models.Submission.id.desc()).all():
        result.append({
            "id": s.id, "task_id": s.task_id, "task_title": s.task.title,
            "employee": s.employee.name, "content": s.content,
            "spent_hours": s.spent_hours, "submitted_at": s.submitted_at.isoformat(),
            "evaluation": _evaluation_out(s.evaluation),
        })
    return result


@admin.post("/submissions/{submission_id}/evaluate")
def evaluate_submission_api(submission_id: int, db: Session = Depends(get_db)):
    """评估引擎：按 TDL 验收标准评分，更新员工画像。"""
    s = db.get(models.Submission, submission_id)
    if not s:
        raise HTTPException(404, "提交不存在")
    if s.evaluation:
        raise HTTPException(400, "该提交已评估过")
    try:
        ev = evaluate.evaluate_submission(db, s)
    except gateway.LLMError as e:
        raise HTTPException(502, f"LLM 评估失败: {e}")
    return _evaluation_out(ev)


# ================================================================ 员工自助
@me.get("/me")
def my_profile(user: models.Employee = Depends(get_current_user)):
    """我的画像：能力分、难度上限、负载、请假状态。"""
    return {
        "id": user.id, "name": user.name, "role": user.role,
        "capability": user.capability, "task_count": user.task_count,
        "current_load": user.current_load, "on_leave": user.on_leave,
        "difficulty_cap": evaluate.suggest_difficulty_cap(user.capability),
    }


@me.get("/me/tasks")
def my_tasks(
    status: str | None = None,
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的任务：已分配给我且已通过审核的任务。"""
    q = db.query(models.Task).filter(
        models.Task.assigned_employee_id == user.id,
        models.Task.review_status == "approved",
    )
    if status:
        q = q.filter(models.Task.status == status)
    return [_task_out(t) for t in q.order_by(models.Task.id.desc()).all()]


@me.get("/me/submissions")
def my_submissions(user: models.Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """我的提交记录 + 评估反馈（只看自己的）。"""
    result = []
    for s in (
        db.query(models.Submission)
        .filter(models.Submission.employee_id == user.id)
        .order_by(models.Submission.id.desc())
        .all()
    ):
        result.append({
            "id": s.id, "task_id": s.task_id, "task_title": s.task.title,
            "content": s.content, "spent_hours": s.spent_hours,
            "submitted_at": s.submitted_at.isoformat(),
            "evaluation": _evaluation_out(s.evaluation),
        })
    return result


class LeaveIn(BaseModel):
    on_leave: bool


@me.post("/me/leave")
def set_leave(data: LeaveIn, user: models.Employee = Depends(get_current_user), db: Session = Depends(get_db)):
    """员工自助请假/销假（影响管理员端的分配建议）。"""
    user.on_leave = data.on_leave
    db.commit()
    return {"ok": True, "on_leave": user.on_leave}


class SubmissionIn(BaseModel):
    content: str
    spent_hours: float = 0.0


@me.post("/me/tasks/{task_id}/submit")
def submit_task(
    task_id: int,
    data: SubmissionIn,
    user: models.Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """员工下班前提交交付物（只能提交分给自己的任务）。"""
    t = db.get(models.Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.assigned_employee_id != user.id:
        raise HTTPException(403, "该任务未分配给你")
    if t.status != "assigned":
        raise HTTPException(400, "任务未处于已分配状态")
    s = models.Submission(
        task_id=task_id,
        employee_id=user.id,
        content=data.content,
        spent_hours=data.spent_hours,
    )
    t.status = "submitted"
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"submission_id": s.id}
