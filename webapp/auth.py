"""
احراز هویت Telegram Mini App.

- validate_init_data: بررسی امضای رسمی initData با BOT_TOKEN (HMAC-SHA256) + auth_date
- issue_token / verify_token: نشست امضاشده‌ی کوتاه‌عمر (HMAC) — کاملاً stdlib
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Dict, Optional
from urllib.parse import parse_qsl

from . import settings


class AuthError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(code)
        self.code = code
        self.message = message or code


def validate_init_data(init_data: str, bot_token: str, max_age: int, now: Optional[int] = None) -> Dict:
    if not init_data or len(init_data) > 4096:
        raise AuthError("invalid_init_data", "اطلاعات ورود نامعتبر است.")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise AuthError("invalid_init_data", "اطلاعات ورود نامعتبر است.")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        raise AuthError("invalid_signature", "امضای ورود نامعتبر است.")
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        raise AuthError("invalid_init_data", "اطلاعات ورود نامعتبر است.")
    now = int(now if now is not None else time.time())
    if auth_date <= 0 or auth_date > now + 60:
        raise AuthError("invalid_init_data", "اطلاعات ورود نامعتبر است.")
    if now - auth_date > max_age:
        raise AuthError("init_data_expired", "نشست منقضی شده؛ مینی‌اپ را دوباره باز کن.")
    try:
        user = json.loads(data.get("user", ""))
        uid = int(user["id"])
    except Exception:
        raise AuthError("invalid_init_data", "اطلاعات کاربر نامعتبر است.")
    user["id"] = uid
    return user


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user_id: int, now: Optional[int] = None, ttl: Optional[int] = None,
                secret: Optional[str] = None) -> str:
    now = int(now if now is not None else time.time())
    payload = _b64(json.dumps({"uid": user_id, "iat": now, "exp": now + (ttl or settings.SESSION_TTL)},
                              separators=(",", ":")).encode())
    sig = _b64(hmac.new((secret or settings.SESSION_SECRET).encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(token: str, now: Optional[int] = None, secret: Optional[str] = None) -> Dict:
    """خروجی: {"uid","iat","exp"}؛ در صورت مشکل AuthError."""
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new((secret or settings.SESSION_SECRET).encode(), payload.encode(),
                                 hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            raise ValueError
        data = json.loads(_unb64(payload))
        uid, iat, exp = int(data["uid"]), int(data["iat"]), int(data["exp"])
    except Exception:
        raise AuthError("unauthorized", "نشست نامعتبر است.")
    if int(now if now is not None else time.time()) >= exp:
        raise AuthError("session_expired", "نشست منقضی شده است.")
    return {"uid": uid, "iat": iat, "exp": exp}
