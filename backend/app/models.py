"""数据模型。

核心对象：
  Project     公司业务项目（大型任务）
  Task        拆解后的天级任务（TDL 实例）
  Submission  员工下班前提交的交付物
  Evaluation  评估引擎的打分结果
  Employee    员工画像（技能 + 能力分 + 负载）
"""
from datetime import datetime, date

from sqlalchemy import String, Text, Integer, Float, JSON, DateTime, Date, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64), default="")          # 岗位
    skills: Mapped[list] = mapped_column(JSON, default=list)           # 技能标签
    capability: Mapped[float] = mapped_column(Float, default=70.0)     # 能力分 0-100（EMA 更新）
    task_count: Mapped[int] = mapped_column(Integer, default=0)        # 已评估任务数
    on_leave: Mapped[bool] = mapped_column(Boolean, default=False)     # 是否请假（影响分配）
    # --- 登录与角色 ---
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)    # 管理员 / 员工
    # --- 排班 ---
    work_pattern: Mapped[str] = mapped_column(String(16), default="standard")   # standard=工作日 | 2on2off=上二休二
    schedule_anchor: Mapped[date | None] = mapped_column(Date, nullable=True)   # 上二休二周期锚点（首个工作日）
    # --- 考勤平台用户映射：{"feishu": "ou_xxx", "dingtalk": "xxx", "wecom": "xxx"} ---
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tasks: Mapped[list["Task"]] = relationship(back_populates="assigned_employee")

    @property
    def current_load(self) -> int:
        """当前未完成任务的负载。"""
        return len([t for t in self.tasks if t.status in ("assigned", "submitted")])


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")                # 项目目的（拆解的关键输入）
    industry: Mapped[str] = mapped_column(String(16), default="knowledge")  # 行业包：knowledge|production|response
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | done
    # 滚动拆解：里程碑计划 [{title, goal, scope_hint, est_days}]
    milestones: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    # --- TDL 字段 ---
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    phase: Mapped[str] = mapped_column(String(200), default="")         # 所属里程碑阶段（滚动拆解用）
    deliverable_type: Mapped[str] = mapped_column(String(16), default="document")  # code|document|data|image
    acceptance: Mapped[list] = mapped_column(JSON, default=list)       # 验收标准列表
    skill_tags: Mapped[list] = mapped_column(JSON, default=list)      # 所需技能标签
    est_hours: Mapped[float] = mapped_column(Float, default=6.0)      # 预估工时
    difficulty: Mapped[int] = mapped_column(Integer, default=3)       # 难度 1-5
    depends_on: Mapped[list] = mapped_column(JSON, default=list)      # 依赖的前置任务（暂存 LLM 生成的标题，审核时人工对齐）
    priority: Mapped[str] = mapped_column(String(4), default="P2")    # P0-P3

    # --- 流程状态 ---
    review_status: Mapped[str] = mapped_column(String(16), default="draft", index=True)  # draft|approved|rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)       # pending|assigned|submitted|reviewed
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="tasks")
    assigned_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    assigned_employee: Mapped["Employee | None"] = relationship(back_populates="tasks")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")             # 交付物内容（文本）
    spent_hours: Mapped[float] = mapped_column(Float, default=0.0)     # 员工自报实际耗时
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["Task"] = relationship(back_populates="submissions")
    employee: Mapped["Employee"] = relationship()
    evaluation: Mapped["Evaluation | None"] = relationship(back_populates="submission", uselist=False, cascade="all, delete-orphan")


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0)    # 质量 0-100
    efficiency_score: Mapped[float] = mapped_column(Float, default=0)  # 效率 0-100
    total_score: Mapped[float] = mapped_column(Float, default=0)      # 总分（质量 70% + 效率 30%）
    feedback: Mapped[str] = mapped_column(Text, default="")             # 可解释反馈（必须给理由）
    # 逐条验收标准判定：[{criterion, verdict: pass|partial|fail, comment}]
    criterion_scores: Mapped[list] = mapped_column(JSON, default=list)
    # 防作弊标记：过短提交 / 与历史提交重复
    flags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    submission: Mapped["Submission"] = relationship(back_populates="evaluation")


class AttendanceRecord(Base):
    """考勤事件：上班/下班打卡。

    source: manual（本系统打卡按钮）/ dingtalk / wecom / feishu（适配器接入后写入）
    """
    __tablename__ = "attendance_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    type: Mapped[str] = mapped_column(String(8))  # in | out
    source: Mapped[str] = mapped_column(String(16), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    employee: Mapped["Employee"] = relationship()
