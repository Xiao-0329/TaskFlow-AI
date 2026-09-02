"""拆解引擎 v2：滚动拆解。

两阶段：
  1. 里程碑规划 —— LLM 把项目切成若干阶段（存 Project.milestones）
  2. 阶段内拆解 —— 只拆"下一个未拆解的阶段"，天级原子任务（Task.phase 标记所属阶段）

滚动规则：上一阶段任务全部被领取（无 pending）后才允许拆下一阶段，
避免远期任务拆细后因需求变化频繁返工。
"""
from sqlalchemy.orm import Session

from .. import models
from ..industry import get_pack
from ..llm import gateway, prompts
from ..tdl import validate_llm_tasks


def _team_context(db: Session) -> str:
    employees = db.query(models.Employee).filter(models.Employee.on_leave.is_(False)).all()
    return "；".join(
        f"{e.name}（{e.role}，技能: {','.join(e.skills) or '未填'}）" for e in employees
    ) or ""


def plan_milestones(db: Session, project: models.Project) -> list[dict]:
    """阶段一：生成里程碑计划（已有则跳过）。注入行业包提示。"""
    if project.milestones:
        return project.milestones
    pack = get_pack(project.industry)
    text = gateway.chat(
        prompts.MILESTONE_SYSTEM,
        prompts.milestone_user(project.name, project.goal, project.description, pack.decompose_hint),
        schema=prompts.MILESTONE_SCHEMA,
    )
    parsed = gateway.parse_json(text)
    milestones = parsed.get("milestones", [])
    if not milestones:
        raise ValueError("LLM 未产出任何里程碑")
    project.milestones = milestones
    db.commit()
    return milestones


def _next_milestone(project: models.Project) -> tuple[dict | None, str | None]:
    """找第一个未拆解的里程碑；同时校验滚动规则（前序阶段无待分配任务）。"""
    decomposed = {t.phase for t in project.tasks if t.phase}
    for m in project.milestones:
        if m["title"] in decomposed:
            # 该阶段已拆解，检查它是否还有未领取的任务（滚动约束）
            pending = [
                t for t in project.tasks
                if t.phase == m["title"] and t.status == "pending" and t.review_status == "approved"
            ]
            if pending:
                return None, f"阶段「{m['title']}」还有 {len(pending)} 个任务待分配，先消化完再拆下一阶段"
            continue
        return m, None
    return None, "所有阶段都已拆解完成"


def decompose_project(db: Session, project: models.Project) -> list[models.Task]:
    """阶段二：拆解下一个未拆解的里程碑（首次调用会先规划里程碑）。"""
    plan_milestones(db, project)
    milestone, err = _next_milestone(project)
    if err:
        raise ValueError(err)
    return _decompose_milestone(db, project, milestone)


def decompose_next_phase(db: Session, project: models.Project) -> list[models.Task]:
    """滚动拆解入口：显式拆下一阶段（带滚动约束校验）。"""
    if not project.milestones:
        plan_milestones(db, project)
    milestone, err = _next_milestone(project)
    if err:
        raise ValueError(err)
    return _decompose_milestone(db, project, milestone)


def _decompose_milestone(db: Session, project: models.Project, milestone: dict) -> list[models.Task]:
    # 前序已完成任务上下文（让 LLM 知道之前做到哪了）
    done_titles = [
        f"{t.title}（{t.status}）" for t in project.tasks if t.phase and t.phase != milestone["title"]
    ]
    done_context = "；".join(done_titles[:15])

    pack = get_pack(project.industry)
    text = gateway.chat(
        prompts.PHASE_DECOMPOSE_SYSTEM,
        prompts.phase_decompose_user(
            project.name, project.goal, milestone, _team_context(db), done_context,
            industry_hint=pack.decompose_hint,
        ),
        schema=prompts.TDL_SCHEMA,
    )
    result = validate_llm_tasks(gateway.parse_json(text))

    tasks = []
    for t in result.tasks:
        task = models.Task(
            project_id=project.id,
            title=t.title,
            description=t.description,
            phase=milestone["title"],
            deliverable_type=t.deliverable_type,
            acceptance=t.acceptance,
            skill_tags=t.skill_tags,
            est_hours=t.est_hours,
            difficulty=t.difficulty,
            depends_on=t.depends_on,
            priority=t.priority,
            review_status="draft",
        )
        db.add(task)
        tasks.append(task)
    db.commit()
    return tasks


def phase_progress(project: models.Project) -> list[dict]:
    """阶段进度视图（管理员项目列表用）。"""
    result = []
    for i, m in enumerate(project.milestones or []):
        phase_tasks = [t for t in project.tasks if t.phase == m["title"]]
        result.append({
            "index": i,
            "title": m["title"],
            "est_days": m.get("est_days"),
            "decomposed": len(phase_tasks) > 0,
            "task_total": len(phase_tasks),
            "task_pending": sum(1 for t in phase_tasks if t.review_status == "approved" and t.status == "pending"),
            "task_done": sum(1 for t in phase_tasks if t.status == "reviewed"),
        })
    return result
