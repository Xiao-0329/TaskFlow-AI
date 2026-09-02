"""评估引擎：按 TDL 验收标准评估提交，更新员工能力画像。"""
import json

from sqlalchemy.orm import Session

from .. import models
from ..industry import get_pack
from ..llm import gateway, prompts

# 能力分 EMA 平滑系数：新评估权重（越小越保守，避免单次评分大幅震荡）
EMA_ALPHA = 0.3

# 难度爬坡目标：让员工接到的任务难度略低于其当前能力对应档位（70% 成功率原则）
DIFFICULTY_CAP = {90: 5, 80: 5, 70: 4, 60: 4, 50: 3, 0: 2}


def evaluate_submission(db: Session, submission: models.Submission) -> models.Evaluation:
    task = submission.task
    tdl_dict = {
        "title": task.title,
        "description": task.description,
        "deliverable_type": task.deliverable_type,
        "acceptance": task.acceptance,
        "difficulty": task.difficulty,
    }

    pack = get_pack(task.project.industry)

    system = prompts.EVALUATE_SYSTEM
    user = prompts.evaluate_user(
        task_json=json.dumps(tdl_dict, ensure_ascii=False),
        submission_content=submission.content,
        spent_hours=submission.spent_hours,
        est_hours=task.est_hours,
        industry_hint=pack.eval_hint,
    )

    text = gateway.chat(system, user, schema=prompts.EVAL_SCHEMA)
    parsed = gateway.parse_json(text)

    quality = _clamp(float(parsed.get("quality_score", 0)))
    efficiency = _clamp(float(parsed.get("efficiency_score", 0)))
    # 行业包权重：生产型重质量（0.8），响应型重效率（0.4）
    total = round(quality * pack.quality_weight + efficiency * pack.efficiency_weight, 1)
    feedback = str(parsed.get("feedback", "")).strip() or "（模型未给出反馈）"

    evaluation = models.Evaluation(
        submission_id=submission.id,
        quality_score=quality,
        efficiency_score=efficiency,
        total_score=total,
        feedback=feedback,
    )
    db.add(evaluation)

    # 更新任务与员工画像
    task.status = "reviewed"
    _update_employee_profile(db, submission.employee, total)

    db.commit()
    db.refresh(evaluation)
    return evaluation


def _update_employee_profile(db: Session, employee: models.Employee, score: float) -> None:
    """EMA 更新能力分 + 更新任务计数。

    评分不直接奖惩难度，只收敛能力区间；分配建议见 recommend 难度上限。
    """
    n = employee.task_count
    # 前 3 次任务用增量平均快速校准，之后用 EMA 平滑
    if n < 3:
        new_score = (employee.capability * n + score) / (n + 1)
    else:
        new_score = employee.capability * (1 - EMA_ALPHA) + score * EMA_ALPHA
    employee.capability = round(_clamp(new_score), 1)
    employee.task_count = n + 1


def suggest_difficulty_cap(capability: float) -> int:
    """根据能力分给出建议的难度上限（难度爬坡，防马太效应）。"""
    for threshold, cap in sorted(DIFFICULTY_CAP.items(), reverse=True):
        if capability >= threshold:
            return cap
    return 2


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))
