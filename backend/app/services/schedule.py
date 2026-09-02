"""排班引擎：日历计算 + 上二休二约束。

模式：
  standard —— 周一到周五上班（法定节假日暂不处理，后续可接节假日 API）
  2on2off  —— 上二休二：以 schedule_anchor 为周期起点，周期内第 1、2 天上班，第 3、4 天休息
"""
from datetime import date, timedelta

from .. import models

PATTERNS = ("standard", "2on2off")

# 上二休二每日工时容量（自动派发用）
DAILY_CAPACITY_HOURS = 8.0


def is_on_duty(employee: models.Employee, day: date | None = None) -> bool:
    """判断员工某天是否排班上班。请假覆盖排班（请假=不上班）。"""
    day = day or date.today()
    if employee.on_leave:
        return False
    if employee.work_pattern == "2on2off":
        anchor = employee.schedule_anchor
        if anchor is None:
            return True  # 未设锚点时默认上班（避免新数据全休）
        offset = (day - anchor).days
        return offset % 4 in (0, 1)
    # standard：工作日
    return day.weekday() < 5


def calendar(employee: models.Employee, days: int = 14, start: date | None = None) -> list[dict]:
    """生成未来 N 天的排班日历（管理员视图用）。"""
    start = start or date.today()
    result = []
    for i in range(days):
        d = start + timedelta(days=i)
        result.append({
            "date": d.isoformat(),
            "weekday": "一二三四五六日"[d.weekday()],
            "on_duty": is_on_duty(employee, d),
        })
    return result


def apply_pattern(employee: models.Employee, pattern: str, anchor: date | None) -> None:
    """设置排班模式；2on2off 需要锚点（首个上班日）。"""
    if pattern not in PATTERNS:
        raise ValueError(f"未知排班模式: {pattern}")
    employee.work_pattern = pattern
    employee.schedule_anchor = anchor if pattern == "2on2off" else None
