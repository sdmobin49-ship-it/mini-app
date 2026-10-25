"""
کاتالوگ فروش: منبع حقیقت همان config.py ربات است (PLANS / TUNNEL_PLANS / UNLIMITED_PLANS).
پلنی که در config کامنت یا حذف شده باشد در Mini App هم دیده نمی‌شود.
"""
from typing import Any, Dict, List, Optional

from config import PLANS, TUNNEL_PLANS, UNLIMITED_PLANS

SERVICE_TYPES = ("cdn", "tunnel", "unlimited")

# پروتکل‌ها دقیقاً همان‌هایی‌اند که Adapterهای پنل هنگام ساخت کاربر می‌فرستند:
# marzban.py → vless+shadowsocks | marzban_tunnel.py → vless | marzban_unlimited.py → vless+shadowsocks
PROTOCOLS = {"cdn": ["vless", "shadowsocks"], "tunnel": ["vless", "shadowsocks"], "unlimited": ["vless", "shadowsocks"]}

TYPE_META = {
    "cdn": {"title": "سرویس حجمی عادی (CDN)", "kind": "volume"},
    "tunnel": {"title": "سرویس حجمی Tunnel Premium", "kind": "volume"},
    "unlimited": {"title": "سرویس نامحدود", "kind": "unlimited"},
}


def _source(service_type: str) -> Dict[str, Dict[str, Any]]:
    return {"cdn": PLANS, "tunnel": TUNNEL_PLANS, "unlimited": UNLIMITED_PLANS}.get(service_type, {})


def get_plan(service_type: str, plan_id: str) -> Optional[Dict[str, Any]]:
    p = _source(service_type).get(plan_id)
    return dict(p) if p else None


def public_plan(service_type: str, plan_id: str, p: Dict[str, Any]) -> Dict[str, Any]:
    unlimited = service_type == "unlimited"
    return {
        "id": plan_id,
        "service_type": service_type,
        "name": p["name"],
        "data_limit_gb": None if unlimited else p.get("data_limit_gb"),   # None = نامحدود
        "duration_days": p["duration_days"],
        "price": p["price"],
        "users": p.get("users"),
        "description": p.get("description"),
        "protocols": PROTOCOLS[service_type],
    }


def list_plans(service_type: Optional[str] = None) -> List[Dict[str, Any]]:
    types = [service_type] if service_type else list(SERVICE_TYPES)
    out = []
    for t in types:
        for pid, p in _source(t).items():
            out.append(public_plan(t, pid, p))
    return out


def plan_label(service_type: str, plan_id: str) -> str:
    """نام پلن؛ برای پلن‌های قدیمی که دیگر در config نیستند (مثل referral_reward) برچسب امن."""
    p = _source(service_type).get(plan_id)
    if p:
        return p["name"]
    return "هدیه رفرال" if plan_id == "referral_reward" else "پلن قدیمی"
