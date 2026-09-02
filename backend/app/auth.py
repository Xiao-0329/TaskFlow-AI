"""轻量鉴权：HMAC 签名 token（MVP 级，无过期，重启不失效）。

角色分两级：
  管理员（is_admin）—— 分配、审核、评估、员工管理
  员工 —— 看自己的任务、提交交付物、看自己的反馈
"""
import hashlib
import hmac
import secrets
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .db import get_db

# 持久化密钥：首次启动生成，存 .secret 文件（重启不掉线）
_SECRET_FILE = Path(__file__).parent.parent / ".secret"


def _load_secret() -> str:
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    s = secrets.token_hex(32)
    _SECRET_FILE.write_text(s)
    return s


SECRET = _load_secret()


def hash_password(pw: str) -> str:
    return hashlib.sha256(f"tf${pw}".encode()).hexdigest()


def make_token(emp_id: int) -> str:
    payload = str(emp_id)
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def verify_token(token: str) -> int | None:
    try:
        emp_id, sig = token.rsplit(".", 1)
        expect = hmac.new(SECRET.encode(), emp_id.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        return int(emp_id)
    except Exception:
        return None


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.Employee:
    if cred is None:
        raise HTTPException(401, "未登录")
    emp_id = verify_token(cred.credentials)
    if emp_id is None:
        raise HTTPException(401, "登录已失效，请重新登录")
    emp = db.get(models.Employee, emp_id)
    if not emp:
        raise HTTPException(401, "用户不存在")
    return emp


def admin_required(user: models.Employee = Depends(get_current_user)) -> models.Employee:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user
