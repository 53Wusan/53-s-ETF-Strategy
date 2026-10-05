from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AlertDelivery


def _signature(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode(), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def signal_card(symbol: str, action: str, score: float, price: float, reason: str, confidence: str, url: str) -> dict:
    color = "red" if action in {"buy", "add"} else "green" if action in {"reduce", "exit"} else "blue"
    return {
        "msg_type": "interactive",
        "card": {
            "header": {"template": color, "title": {"tag": "plain_text", "content": f"{symbol} · {action.upper()} 信号"}},
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**贪恐值**\n{score:.1f}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**价格**\n{price:.2f}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**置信度**\n{confidence}"}},
                    ],
                },
                {"tag": "div", "text": {"tag": "lark_md", "content": reason}},
                {"tag": "action", "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "打开看板"}, "url": url, "type": "primary"}]},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "研究与纪律工具，不构成投资建议，也不会自动下单。"}]},
            ],
        },
    }


def send_once(db: Session, dedup_key: str, event_type: str, payload: dict) -> AlertDelivery:
    existing = db.scalar(select(AlertDelivery).where(AlertDelivery.dedup_key == dedup_key))
    if existing:
        return existing
    delivery = AlertDelivery(dedup_key=dedup_key, event_type=event_type, payload=payload)
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    settings = get_settings()
    if not settings.feishu_webhook_url:
        delivery.status = "skipped"
        delivery.last_error = "FEISHU_WEBHOOK_URL 未配置"
        db.commit()
        return delivery
    body = dict(payload)
    if settings.feishu_webhook_secret:
        timestamp = str(int(time.time()))
        body.update({"timestamp": timestamp, "sign": _signature(settings.feishu_webhook_secret, timestamp)})
    try:
        delivery.attempts += 1
        response = httpx.post(settings.feishu_webhook_url, json=body, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("code", data.get("StatusCode", 0)) not in (0, None):
            raise RuntimeError(str(data))
        delivery.status = "sent"
        delivery.sent_at = datetime.now(timezone.utc)
        delivery.last_error = ""
    except Exception as exc:  # notification failures must not abort signal persistence
        delivery.status = "failed"
        delivery.last_error = str(exc)[:1000]
    db.commit()
    return delivery


def send_error(db: Session, key: str, title: str, detail: str) -> AlertDelivery:
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"template": "orange", "title": {"tag": "plain_text", "content": title}},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": detail[:2500]}},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "数据异常期间不会生成新交易信号。"}]},
            ],
        },
    }
    return send_once(db, key, "data_error", payload)

