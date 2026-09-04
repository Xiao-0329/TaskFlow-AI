from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import models  # noqa: F401
from .auth import hash_password
from .db import engine, SessionLocal
from .api import routes, attendance, webhooks

app = FastAPI(title="TaskFlow AI —— AI 任务分配系统", version="0.7.0")
app.include_router(routes.public)
app.include_router(routes.admin)
app.include_router(routes.me)
app.include_router(attendance.router)
app.include_router(webhooks.router)

STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


def _migrate_sqlite() -> None:
    """SQLite 轻量迁移：为已有表补充新列（MVP 阶段免 alembic）。"""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(employees)"))]
        if "username" not in cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN username VARCHAR(64)"))
        if "password_hash" not in cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN password_hash VARCHAR(128)"))
        if "is_admin" not in cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
        if "work_pattern" not in cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN work_pattern VARCHAR(16) DEFAULT 'standard'"))
        if "schedule_anchor" not in cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN schedule_anchor DATE"))
        if "external_ids" not in cols:
            conn.execute(text("ALTER TABLE employees ADD COLUMN external_ids JSON"))
        task_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(tasks)"))]
        if "phase" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN phase VARCHAR(200) DEFAULT ''"))
        proj_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(projects)"))]
        if "milestones" not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN milestones JSON"))
        if "industry" not in proj_cols:
            conn.execute(text("ALTER TABLE projects ADD COLUMN industry VARCHAR(16) DEFAULT 'knowledge'"))
        ev_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(evaluations)"))]
        if "criterion_scores" not in ev_cols:
            conn.execute(text("ALTER TABLE evaluations ADD COLUMN criterion_scores JSON"))
        if "flags" not in ev_cols:
            conn.execute(text("ALTER TABLE evaluations ADD COLUMN flags JSON"))
        conn.commit()


@app.on_event("startup")
def on_startup():
    models.Base.metadata.create_all(bind=engine)
    _migrate_sqlite()

    # 首次启动：写入演示员工 + 管理员账号
    from . import models as m
    with SessionLocal() as db:
        if db.query(m.Employee).count() == 0:
            demo = [
                m.Employee(name="张工", role="后端开发", skills=["python", "开发", "api"], username="zhang"),
                m.Employee(name="李工", role="前端开发", skills=["javascript", "开发", "设计"], username="li"),
                m.Employee(name="王敏", role="测试工程师", skills=["测试", "文档"], username="wang"),
                m.Employee(name="赵文", role="产品经理", skills=["调研", "文档", "设计"], username="zhao"),
            ]
            for e in demo:
                e.password_hash = hash_password("123456")
            db.add_all(demo)
            db.commit()

        # 补齐存量员工缺失的登录信息（默认密码 123456）
        for e in db.query(m.Employee).all():
            changed = False
            if not e.username:
                e.username = e.name  # 中文姓名可直接作为登录名
                changed = True
            if not e.password_hash:
                e.password_hash = hash_password("123456")
                changed = True
            if changed:
                db.commit()

        # 确保存在管理员账号（admin / admin123）
        if not db.query(m.Employee).filter(m.Employee.is_admin.is_(True)).count():
            db.add(m.Employee(
                name="管理员", role="管理员", username="admin",
                password_hash=hash_password("admin123"), is_admin=True,
            ))
            db.commit()
