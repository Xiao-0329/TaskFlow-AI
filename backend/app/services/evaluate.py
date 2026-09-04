"""评估引擎：按 TDL 验收标准评估提交，更新员工能力画像。

可解释性：每次评估包含逐条验收标准的 pass/partial/fail 判定与依据。
防作弊：过短提交、与本人历史提交重复会打标记并影响评分。
"""
import json

from sqlalchemy.orm import Session

from .. import models
from ..industry import get_pack
from ..llm import gateway, prompts

# 能力分 EMA 平滑系数：新评估权重（越小越保守，避免单次评分大幅震荡）
EMA_ALPHA = 0.3

# 难度爬坡目标：让员工接到的任务难度略低于其当前能力对应档位（70% 成功率原则）
DIFFICULTY_CAP = {90: 5, 80: 5, 70: 4, 60: 4, 50: 3, 0: 2}

# 防作弊阈值
MIN_CONTENT_LEN = 30        # 低于此字数视为可疑敷衍提交
DUPLICATE_PENALTY = 25      # 疑似重复提交的质量分惩罚


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

    # ---- 防作弊检测（LLM 评分前的客观检查）----
    flags = _detect_gaming(db, submission)

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

    # 防作弊惩罚：重复提交直接扣质量分；过短提交交给 LLM 判（评分时已能看到原文）
    if "duplicate_submission" in flags:
        quality = _clamp(quality - DUPLICATE_PENALTY)

    # 行业包权重：生产型重质量（0.8），响应型重效率（0.4）
    total = round(quality * pack.quality_weight + efficiency * pack.efficiency_weight, 1)
    feedback = str(parsed.get("feedback", "")).strip() or "（模型未给出反馈）"
    if flags:
        feedback = "⚠ " + "；".join(flags) + "\n" + feedback

    # 逐条验收标准判定（LLM 返回的 criteria）
    criteria = _sanitize_criteria(parsed.get("criteria", []), task.acceptance)

    evaluation = models.Evaluation(
        submission_id=submission.id,
        quality_score=quality,
        efficiency_score=efficiency,
        total_score=total,
        feedback=feedback,
        criterion_scores=criteria,
        flags=flags,
    )
    db.add(evaluation)

    # 更新任务与员工画像
    task.status = "reviewed"
    _update_employee_profile(db, submission.employee, total)

    db.commit()
    db.refresh(evaluation)
    return evaluation


def _detect_gaming(db: Session, submission: models.Submission) -> list[str]:
    """客观防作弊检查：过短提交、与本人历史提交高度重复。"""
    flags = []
    content = (submission.content or "").strip()

    if len(content) < MIN_CONTENT_LEN:
        flags.append(f"可疑敷衍提交：交付物仅 {len(content)} 字（低于 {MIN_CONTENT_LEN} 字阈值）")

    # 与本人（近 10 次）历史提交重复度检查：去空白后完全相同即视为重复
    if content:
        history = (
            db.query(models.Submission)
            .filter(
                models.Submission.employee_id == submission.employee_id,
                models.Submission.id != submission.id,
            )
            .order_by(models.Submission.id.desc())
            .limit(10)
            .all()
        )
        normalized = _normalize(content)
        for h in history:
            if _normalize(h.content or "") == normalized:
                flags.append("重复提交：与本人历史提交内容一致")
                break

    return flags


def _normalize(s: str) -> str:
    """归一化：去所有空白字符后比较（防止加空格绕过重复检测）。"""
    return "".join(s.split())


def _sanitize_criteria(raw: list, acceptance: list[str]) -> list[dict]:
    """清洗 LLM 返回的逐条判定：verdict 规范化、条数对齐验收标准。"""
    result = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict", "")).lower()
        if verdict not in ("pass", "partial", "fail"):
            verdict = "partial"
        criterion = str(item.get("criterion", "")).strip()
        if not criterion:
            continue
        key = _normalize(criterion)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "criterion": criterion,
            "verdict": verdict,
            "comment": str(item.get("comment", "")).strip(),
        })

    # LLM 漏评的验收标准补成未判定（保证员工看到的条数与任务定义一致）
    judged = {_normalize(r["criterion"]) for r in result}
    for acc in acceptance or []:
        if _normalize(acc) not in judged:
            result.append({
                "criterion": acc,
                "verdict": "partial",
                "comment": "（模型未对此条给出判定，已标记为存疑）",
            })
    return result


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
