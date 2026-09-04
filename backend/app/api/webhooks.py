"""考勤 webhook：接收外部考勤平台的打卡事件，驱动任务派发。

三条通道，全部汇入同一个内部处理函数：
  1. POST /api/webhooks/attendance —— 统一事件 API（任何系统都能对接，共享密钥认证）
  2. POST /api/webhooks/feishu     —— 飞书事件订阅（URL 验证 + 考勤事件）
  3. POST /api/webhooks/dingtalk   —— 钉钉事件回调

  企业微信需要 AES 消息加解密（WXBizMsgCrypt），暂未内置：
  可先用统一事件 API 由企业侧脚本转发（见 README）。

处理逻辑与手动打卡一致：
  上班(in)  → 记录考勤 + 自动派发当日任务
  下班(out) → 记录考勤（当日汇总由员工端/管理员端查看）
"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config, models
from ..db import get_db
from ..services import dispatch

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

SUPPORTED_SOURCES = ("feishu", "dingtalk", "wecom", "generic")


# ================================================================ 核心处理
def _process_attendance_event(
    db: Session, source: str, external_id: str | None, employee_id: int | None, evt_type: str
) -> dict:
    """统一入口：external_id 或 employee_id 定位员工 → 记录考勤 → 派发。"""
    if evt_type not in ("in", "out"):
        raise HTTPException(400, f"type 必须是 in/out，收到: {evt_type}")

    employee = None
    if employee_id:
        employee = db.get(models.Employee, employee_id)
    elif external_id:
        # 内存匹配（SQLite JSON 路径查询方言差异大；MVP 规模直接扫描即可）
        for e in db.query(models.Employee).all():
            ids = e.external_ids or {}
            if ids.get(source) == external_id:
                employee = e
                break

    if not employee:
        # 返回 200 + matched:false，避免外部平台无限重试；绑定信息见管理端
        return {"matched": False, "note": f"未找到 external_id={external_id} 对应的员工，请在管理端绑定"}

    rec = models.AttendanceRecord(employee_id=employee.id, type=evt_type, source=source)
    db.add(rec)

    dispatched = []
    if evt_type == "in":
        dispatched = dispatch.auto_dispatch(db, employee)
    else:
        db.commit()

    return {
        "matched": True,
        "employee": employee.name,
        "type": evt_type,
        "dispatched": [
            {"id": t.id, "title": t.title, "est_hours": t.est_hours}
            for t in dispatched
        ],
    }


# ================================================================ 1. 统一事件 API
class GenericEvent(BaseModel):
    source: str = "generic"       # feishu | dingtalk | wecom | generic
    external_id: str | None = None
    employee_id: int | None = None  # 直连场景（已知系统内员工ID）
    type: str                     # in | out


@router.post("/attendance")
def attendance_webhook(
    event: GenericEvent,
    x_webhook_secret: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """统一考勤事件 API：客户侧任何系统都能 POST 最简 JSON 对接。

    认证：请求头 X-Webhook-Secret（环境变量 ATTENDANCE_WEBHOOK_SECRET，生产必设）。
    """
    if not config.ATTENDANCE_WEBHOOK_SECRET:
        raise HTTPException(503, "未配置 ATTENDANCE_WEBHOOK_SECRET，统一事件 API 未开放")
    if not hmac.compare_digest(x_webhook_secret, config.ATTENDANCE_WEBHOOK_SECRET):
        raise HTTPException(401, "密钥错误")

    source = event.source if event.source in SUPPORTED_SOURCES else "generic"
    if not event.external_id and not event.employee_id:
        raise HTTPException(400, "external_id 与 employee_id 至少提供一个")

    return _process_attendance_event(db, source, event.external_id, event.employee_id, event.type)


# ================================================================ 2. 飞书事件订阅
@router.post("/feishu")
async def feishu_webhook(request: Request, db: Session = Depends(get_db)):
    """飞书事件订阅回调。

    配置：飞书开放平台 → 事件订阅 → 请求地址填 https://<host>/api/webhooks/feishu
    事件：订阅「考勤打卡」相关事件（hr.attendance.*）。
    """
    body = await request.json()

    # URL 验证（配置订阅地址时飞书会先发这个）
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # 事件 token 校验（若配置了 Verification Token）
    token = ""
    header = body.get("header", {})
    if isinstance(header, dict):
        token = header.get("token", "")
    if config.FEISHU_VERIFICATION_TOKEN and token and not hmac.compare_digest(
        token, config.FEISHU_VERIFICATION_TOKEN
    ):
        raise HTTPException(401, "Verification Token 不匹配")

    event_type = header.get("event_type", "") or body.get("EventType", "")
    event = body.get("event", {})

    # 提取用户 ID：兼容不同版本的事件结构
    external_id = (
        event.get("employee_id")
        or event.get("user_id")
        or event.get("open_id")
        or (event.get("employee", {}) or {}).get("user_id")
    )
    if not external_id:
        return {"code": 0, "msg": "事件中未找到用户标识，忽略"}

    # 判定上下班：事件类型含 clockin/checkin → in；含 clockout/checkout → out
    et = event_type.lower()
    if "clockout" in et or "checkout" in et or "leave" in et:
        evt_type = "out"
    elif "clockin" in et or "checkin" in et:
        evt_type = "in"
    else:
        record = str(event.get("record_type", event.get("type", ""))).lower()
        evt_type = "out" if "out" in record else "in"

    result = _process_attendance_event(db, "feishu", external_id, None, evt_type)
    return {"code": 0, "msg": "ok", **result}


# ================================================================ 3. 钉钉事件回调
@router.post("/dingtalk")
async def dingtalk_webhook(request: Request, db: Session = Depends(get_db)):
    """钉钉事件订阅回调（HTTP 模式）。

    配置：钉钉开放平台 → 事件订阅 → HTTP 回调模式，地址填 https://<host>/api/webhooks/dingtalk
    注意：钉钉考勤数据部分场景只支持 API 拉取；若事件不含打卡类型，默认按上班处理。
    """
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "msg": "invalid json"}

    # 钉钉回调可能带 v2 结构 {"eventMessage": ...} 或扁平结构
    payload = body.get("eventMessage", body)
    event_type = str(body.get("EventType", payload.get("EventType", ""))).lower()

    external_id = (
        payload.get("staffId")
        or payload.get("userid")
        or payload.get("user_id")
        or payload.get("employeeId")
    )
    if not external_id:
        # 无用户标识的事件（如订阅确认）直接确认
        return {"success": True}

    if "clockout" in event_type or "checkout" in event_type or "offjob" in event_type:
        evt_type = "out"
    elif "clockin" in event_type or "checkin" in event_type or "onjob" in event_type:
        evt_type = "in"
    else:
        evt_type = "in"

    result = _process_attendance_event(db, "dingtalk", external_id, None, evt_type)
    return {"success": True, **result}


# ================================================================ 管理端：绑定外部账号（在 routes.py 的 admin router 中暴露）
class ExternalIdIn(BaseModel):
    platform: str   # feishu | dingtalk | wecom
    external_id: str


def bind_external_id(db: Session, employee_id: int, platform: str, external_id: str) -> dict:
    """给员工绑定考勤平台账号（供管理员 API 调用）。"""
    if platform not in ("feishu", "dingtalk", "wecom"):
        raise HTTPException(400, "platform 必须是 feishu / dingtalk / wecom")
    e = db.get(models.Employee, employee_id)
    if not e:
        raise HTTPException(404, "员工不存在")
    ids = dict(e.external_ids or {})
    if external_id:
        ids[platform] = external_id
    else:
        ids.pop(platform, None)
    e.external_ids = ids
    db.commit()
    return {"ok": True, "external_ids": ids}
