"""اتصال به پنل Marzban سرویس Tunnel Premium."""
import aiohttp
import time
import logging
import json
from typing import Optional, Dict, Any
from config import TUNNEL_PANEL_URL, TUNNEL_PANEL_USERNAME, TUNNEL_PANEL_PASSWORD

logger = logging.getLogger(__name__)

_token: Optional[str] = None
_token_expiry: float = 0


async def get_token() -> str:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry:
        return _token
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{TUNNEL_PANEL_URL}/api/admin/token",
            data={"username": TUNNEL_PANEL_USERNAME, "password": TUNNEL_PANEL_PASSWORD},
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


async def create_user(username: str, data_limit_gb: int, duration_days: int) -> Dict[str, Any]:
    expire_timestamp = int(time.time()) + (duration_days * 86400)
    data_limit_bytes = data_limit_gb * 1024 * 1024 * 1024
    payload = {
        "username": username,
        "proxies": {
            "vless": {},
            "shadowsocks": {}
        },
        "inbounds": {},
        "expire": expire_timestamp,
        "data_limit": data_limit_bytes,
        "data_limit_reset_strategy": "no_reset",
        "status": "active",
        "group_ids": [1, 3]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{TUNNEL_PANEL_URL}/api/user",
            json=payload,
            headers=await _headers(),
            ssl=True
        ) as resp:
            text = await resp.text()
            if resp.status in (200, 201):
                return json.loads(text)
            logger.error(f"Tunnel create user error: {resp.status} - {text}")
            raise Exception(f"خطا در ساخت کاربر Tunnel: {resp.status} - {text}")


async def get_user(username: str) -> Optional[Dict]:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TUNNEL_PANEL_URL}/api/user/{username}",
            headers=await _headers(),
            ssl=True
        ) as resp:
            if resp.status in (200, 201):
                return await resp.json()
            return None


async def delete_user(username: str) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{TUNNEL_PANEL_URL}/api/user/{username}",
            headers=await _headers(),
            ssl=True
        ) as resp:
            return resp.status in (200, 204)


async def reset_user_traffic(username: str) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{TUNNEL_PANEL_URL}/api/user/{username}/reset",
            headers=await _headers(),
            ssl=True
        ) as resp:
            return resp.status in (200, 204)


async def modify_user(username: str, **kwargs) -> Optional[Dict]:
    user = await get_user(username)
    if not user:
        return None
    user.update(kwargs)
    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{TUNNEL_PANEL_URL}/api/user/{username}",
            json=user,
            headers=await _headers(),
            ssl=True
        ) as resp:
            if resp.status in (200, 201):
                return await resp.json()
            return None


async def get_system_stats() -> Dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TUNNEL_PANEL_URL}/api/system",
            headers=await _headers(),
            ssl=True
        ) as resp:
            return await resp.json()


async def get_all_users() -> list:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{TUNNEL_PANEL_URL}/api/users?limit=1000",
            headers=await _headers(),
            ssl=True
        ) as resp:
            data = await resp.json()
            return data.get("users", [])


async def set_user_limits(username: str, expire_ts: int, data_limit_gb: Optional[int] = None) -> Optional[Dict]:
    """
    تنظیم مطلق تاریخ انقضا (و در صورت نیاز حجم) + فعال‌سازی مجدد.
    چون مقدار «مطلق» است، تکرار امن دارد (برای تمدید Mini App با تلاش مجدد).
    """
    kwargs = {"expire": int(expire_ts), "status": "active"}
    if data_limit_gb is not None:
        kwargs["data_limit"] = int(data_limit_gb) * 1024 * 1024 * 1024
    return await modify_user(username, **kwargs)
