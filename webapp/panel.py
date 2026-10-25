"""
Adapter پنل VPN برای Mini App.

عملیات منطقی (وضعیت/مصرف، ساخت، تمدید) به ماژول‌های واقعی پروژه نگاشت می‌شوند:
marzban.py (CDN)، marzban_tunnel.py (Tunnel)، marzban_unlimited.py (نامحدود).
هیچ آدرس/توکن/اطلاعات پنل به فرانت‌اند نمی‌رسد.
"""
import random
import string
import time
from typing import Any, Dict, Optional

import marzban
import marzban_tunnel
import marzban_unlimited
from config import USER_TAG, UNLIMITED_USER_TAG, TUNNEL_USER_TAG
from core_helpers import parse_expire

_MODULES = {"cdn": marzban, "tunnel": marzban_tunnel, "unlimited": marzban_unlimited}


def resolve_type(panel_username: str, stored_type: Optional[str]) -> str:
    """
    نوع سرویس: اول ستون service_type (cdn/tunnel/unlimited)، وگرنه پیشوند یوزرنیم.
    (سرویس‌های قدیمی با پیشوند SPIDER و service_type=paid/free در پنل حجمی‌اند.)
    """
    if stored_type in _MODULES:
        return stored_type
    if panel_username.startswith(UNLIMITED_USER_TAG):
        return "unlimited"
    if panel_username.startswith(TUNNEL_USER_TAG):
        return "tunnel"
    return "cdn"


def new_username(service_type: str) -> str:
    tag = {"cdn": USER_TAG, "tunnel": TUNNEL_USER_TAG, "unlimited": UNLIMITED_USER_TAG}[service_type]
    return tag + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


async def fetch_user(service_type: str, username: str) -> Optional[Dict[str, Any]]:
    """دیکشنری کاربر در پنل، یا None اگر پنل کاربر را برنگرداند. خطای شبکه/احراز هویت exception می‌دهد."""
    return await _MODULES[service_type].get_user(username)


async def create_user(service_type: str, username: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    m = _MODULES[service_type]
    if service_type == "unlimited":
        return await m.create_user(username, plan["duration_days"])
    return await m.create_user(username, plan["data_limit_gb"], plan["duration_days"])


async def reset_traffic(service_type: str, username: str) -> bool:
    m = _MODULES[service_type]
    return bool(await m.reset_user_traffic(username)) if hasattr(m, "reset_user_traffic") else True


async def set_limits(service_type: str, username: str, expire_ts: int, data_limit_gb: Optional[int]):
    return await _MODULES[service_type].set_user_limits(username, expire_ts, data_limit_gb)


def normalize(ud: Dict[str, Any], now: Optional[int] = None) -> Dict[str, Any]:
    """نرمال‌سازی پاسخ پنل. limit_bytes=None یعنی نامحدود (data_limit خالی/۰ در مرزبان)."""
    now = int(now if now is not None else time.time())
    used = int(ud.get("used_traffic") or 0)
    limit = int(ud.get("data_limit") or 0)
    limit_bytes = limit if limit > 0 else None
    expire_ts = parse_expire(ud.get("expire")) or None
    status = ud.get("status") or "unknown"
    if status == "active" and expire_ts and expire_ts <= now:
        status = "expired"
    return {
        "status": status,
        "used_bytes": used,
        "limit_bytes": limit_bytes,
        "remaining_bytes": None if limit_bytes is None else max(0, limit_bytes - used),
        "expire_ts": expire_ts,
        "days_left": None if not expire_ts else max(0, (expire_ts - now) // 86400),
        "protocols": sorted((ud.get("proxies") or {}).keys()),
    }
