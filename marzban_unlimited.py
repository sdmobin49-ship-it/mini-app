"""
اتصال به پنل مرزبان نامحدود — جداگانه از پنل حجمی
"""
import aiohttp
import time
import logging
import json
from typing import Optional, Dict, Any
from config import UNLIMITED_PANEL_URL, UNLIMITED_PANEL_USERNAME, UNLIMITED_PANEL_PASSWORD

logger = logging.getLogger(__name__)

_token: Optional[str] = None
_token_expiry: float = 0


async def get_token() -> str:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry:
        return _token
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{UNLIMITED_PANEL_URL}/api/admin/token",
            data={"username": UNLIMITED_PANEL_USERNAME, "password": UNLIMITED_PANEL_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            ssl=True
        ) as resp:
            data = await resp.json()
            _token = data["access_token"]
            _token_expiry = time.time() + 3600
            return _token


async def _headers() -> Dict:
    token = await get_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def create_user(username: str, duration_days: int) -> Dict[str, Any]:
    """
    ساخت کاربر نامحدود — data_limit=0 یعنی نامحدود در مرزبان
    """
    expire_timestamp = int(time.time()) + (duration_days * 86400)

    payload = {
        "username": username,
        "proxies": {
            "vless": {},
            "shadowsocks": {}
        },
        "inbounds": {},
        "expire": expire_timestamp,
        "data_limit": 0,              # نامحدود
        "data_limit_reset_strategy": "no_reset",
        "status": "active",
        "group_ids": [1]              # در صورت نیاز تغییر بده
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{UNLIMITED_PANEL_URL}/api/user",
            json=payload,
            headers=await _headers(),
            ssl=True
        ) as resp:
            text = await resp.text()
            if resp.status in (200, 201):
                return json.loads(text)
            else:
                logger.error(f"Unlimited create user error: {resp.status} - {text}")
                raise Exception(f"خطا در ساخت کاربر نامحدود: {resp.status} - {text}")


async def get_user(username: str) -> Optional[Dict]:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{UNLIMITED_PANEL_URL}/api/user/{username}",
            headers=await _headers(),
            ssl=True
        ) as resp:
            if resp.status in (200, 201):
                return await resp.json()
            return None


async def renew_user(username: str, extra_days: int) -> Dict[str, Any]:
    """
    تمدید اشتراک نامحدود — expire فعلی + روزهای جدید
    اگه اشتراک منقضی شده باشه از الان + روزهای جدید حساب میشه
    """
    user = await get_user(username)
    if not user:
        raise Exception(f"کاربر {username} پیدا نشد")

    current_expire = user.get("expire")
    now_ts = int(time.time())

    if current_expire:
        # تبدیل ISO string به timestamp اگه لازم باشه
        if isinstance(current_expire, str):
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(current_expire.replace("Z", "+00:00"))
            current_ts = int(dt.timestamp())
        else:
            current_ts = int(current_expire)
        # اگه منقضی شده از الان حساب کن
        base_ts = max(current_ts, now_ts)
    else:
        base_ts = now_ts

    new_expire = base_ts + (extra_days * 86400)
    user["expire"] = new_expire

    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{UNLIMITED_PANEL_URL}/api/user/{username}",
            json=user,
            headers=await _headers(),
            ssl=True
        ) as resp:
            text = await resp.text()
            if resp.status in (200, 201):
                return json.loads(text)
            else:
                raise Exception(f"خطا در تمدید: {resp.status} - {text}")


async def get_system_stats() -> Dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{UNLIMITED_PANEL_URL}/api/system",
            headers=await _headers(),
            ssl=True
        ) as resp:
            return await resp.json()


async def get_all_users() -> list:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{UNLIMITED_PANEL_URL}/api/users?limit=1000",
            headers=await _headers(),
            ssl=True
        ) as resp:
            data = await resp.json()
            return data.get("users", [])


async def modify_user(username: str, **kwargs) -> Optional[Dict]:
    user = await get_user(username)
    if not user:
        return None
    user.update(kwargs)
    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{UNLIMITED_PANEL_URL}/api/user/{username}",
            json=user,
            headers=await _headers(),
            ssl=True
        ) as resp:
            if resp.status in (200, 201):
                return await resp.json()
            return None


async def set_user_limits(username: str, expire_ts: int, data_limit_gb: Optional[int] = None) -> Optional[Dict]:
    """تنظیم مطلق انقضا + فعال‌سازی (نامحدود: data_limit دست نمی‌خورد). تکرار امن است."""
    return await modify_user(username, expire=int(expire_ts), status="active")
