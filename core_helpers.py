"""
توابع مشترک بین ربات (handlers.py) و Mini App (webapp/).
این توابع عیناً از handlers.py منتقل شده‌اند تا Mini App به aiogram وابسته نباشد؛
handlers.py همین نام‌ها را از اینجا import می‌کند و رفتار ربات تغییر نمی‌کند.
"""
from datetime import datetime, timezone, timedelta

import marzban
import marzban_tunnel
import marzban_unlimited
import database as db
from config import UNLIMITED_USER_TAG, TUNNEL_USER_TAG

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def bytes_to_gb(b: int) -> float:
    return round(b / (1024 ** 3), 2)


def parse_expire(expire_raw) -> int:
    """تبدیل expire به timestamp - چون PasarGuard رشته ISO میده و مرزبان عدد"""
    if not expire_raw:
        return 0
    if isinstance(expire_raw, (int, float)):
        return int(expire_raw)
    if isinstance(expire_raw, str):
        try:
            dt = datetime.fromisoformat(expire_raw.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except Exception:
            return 0
    return 0


def format_expire(expire_raw) -> str:
    ts = parse_expire(expire_raw)
    if not ts:
        return "نامحدود"
    return datetime.fromtimestamp(ts, tz=TEHRAN_TZ).strftime("%Y/%m/%d - %H:%M")


def days_remaining(expire_raw) -> int:
    ts = parse_expire(expire_raw)
    if not ts:
        return 9999
    remaining = ts - int(datetime.now(tz=timezone.utc).timestamp())
    return max(0, remaining // 86400)


def panel_for_username(username: str):
    if username.startswith(UNLIMITED_USER_TAG):
        return marzban_unlimited
    if username.startswith(TUNNEL_USER_TAG):
        return marzban_tunnel
    return marzban


async def get_discount_for_user(code: str, user_id: int):
    """
    اعتبارسنجی کد تخفیف برای یک کاربر.
    خروجی: (ok: bool, message: str, percent: int)
    """
    data = await db.get_discount_code(code)
    if not data:
        return False, "❌ کد تخفیف یافت نشد.", 0
    if not data["is_active"]:
        return False, "❌ این کد تخفیف غیرفعال شده است.", 0
    if data["expires_at"]:
        try:
            exp_dt = datetime.fromisoformat(data["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(tz=timezone.utc) > exp_dt:
                return False, "❌ این کد تخفیف منقضی شده است.", 0
        except Exception:
            pass
    used_count = await db.get_user_code_usage_count(code, user_id)
    if used_count >= data["max_per_user"]:
        return False, "❌ شما قبلاً سقف استفاده از این کد را پر کرده‌اید.", 0
    return True, "", data["percent"]


def apply_discount(price: int, percent: int) -> int:
    return max(0, int(price - (price * percent / 100)))
