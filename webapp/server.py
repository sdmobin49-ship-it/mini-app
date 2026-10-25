"""
سرور HTTP مینی‌اپ (aiohttp.web) — روی همان event loop و همان پروسه‌ی ربات.
پاسخ‌ها: {"ok": true, "data": ...} یا {"ok": false, "error": {"code", "message"}}
"""
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple

from aiohttp import web

import database as db
from config import BOT_TOKEN, FORCE_JOIN_CHANNEL

from . import auth, catalog, service, settings, store
from .auth import AuthError
from .service import ApiError

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

PUBLIC_PATHS = {"/api/v1/auth/telegram", "/health"}


# ─────────────────────────── Rate limiting (حافظه‌ای) ───────────────────────────
class RateLimiter:
    def __init__(self):
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def check(self, key: str, bucket: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        q = self._hits[(key, bucket)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self._hits) > 20000:      # جلوگیری از رشد بی‌پایان حافظه
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > 300][:5000]:
                self._hits.pop(k, None)
        return True


LIMITER = RateLimiter()
# (bucket, limit, window_seconds) برای مسیرهای حساس؛ بقیه: general
SENSITIVE = {
    ("POST", "orders"): ("orders", 15, 60),
    ("POST", "payment"): ("payment", 10, 60),
    ("POST", "config"): ("config", 20, 60),
    ("POST", "tickets"): ("tickets", 10, 3600),
    ("POST", "quote"): ("quote", 30, 60),
}


def _client_ip(request: web.Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[0].strip() if xff else (request.remote or "?"))[:64]


def ok(data: Any = None, status: int = 200) -> web.Response:
    return web.json_response({"ok": True, "data": data}, status=status, headers={"Cache-Control": "no-store"})


def fail(code: str, message: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": {"code": code, "message": message}}, status=status,
                             headers={"Cache-Control": "no-store"})


# ─────────────────────────── Middlewares ───────────────────────────
@web.middleware
async def security_headers(request: web.Request, handler):
    resp = await handler(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "frame-ancestors https://web.telegram.org https://webk.telegram.org https://webz.telegram.org "
        "https://*.telegram.org")
    return resp


@web.middleware
async def errors(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as e:
        return fail(e.code, e.message, e.status)
    except AuthError as e:
        return fail(e.code, e.message, 401)
    except web.HTTPRequestEntityTooLarge:
        return fail("payload_too_large", "حجم درخواست بیش از حد مجاز است.", 413)
    except web.HTTPException as e:
        if request.path.startswith("/api/"):
            return fail("http_error", e.reason or "خطا", e.status)
        raise
    except Exception:
        logger.exception("unhandled error on %s %s", request.method, request.path)   # stack فقط در لاگ سرور
        return fail("internal_error", "خطای داخلی؛ کمی بعد دوباره تلاش کن.", 500)


@web.middleware
async def authenticate(request: web.Request, handler):
    path = request.path
    if not path.startswith("/api/") or path in PUBLIC_PATHS:
        if path == "/api/v1/auth/telegram":
            if not LIMITER.check(_client_ip(request), "auth", 20, 60):
                return fail("rate_limited", "درخواست‌های زیادی ارسال شد؛ کمی صبر کن.", 429)
        return await handler(request)
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("unauthorized", "ابتدا وارد شو.")
    claims = auth.verify_token(header[7:].strip())
    if claims["iat"] < await store.get_min_iat(claims["uid"]):
        raise AuthError("session_revoked", "نشست ابطال شده است.")
    request["uid"] = claims["uid"]
    last = path.rstrip("/").split("/")[-1]
    bucket = SENSITIVE.get((request.method, last))
    if bucket is None and request.method == "POST" and path.endswith("/payment"):
        bucket = SENSITIVE[("POST", "payment")]
    name, limit, window = bucket or ("general", 180, 60)
    if not LIMITER.check(str(claims["uid"]), name, limit, window):
        return fail("rate_limited", "درخواست‌های زیادی ارسال شد؛ کمی صبر کن.", 429)
    return await handler(request)


# ─────────────────────────── Helpers ───────────────────────────
def _page(request: web.Request) -> Tuple[int, int]:
    try:
        limit = max(1, min(50, int(request.query.get("limit", 20))))
        offset = max(0, int(request.query.get("offset", 0)))
    except ValueError:
        raise ApiError("invalid_pagination", "پارامتر صفحه‌بندی نامعتبر است.")
    return limit, offset


def _int(request: web.Request, name: str) -> int:
    try:
        return int(request.match_info[name])
    except (KeyError, ValueError):
        raise ApiError("invalid_id", "شناسه نامعتبر است.")


async def _json(request: web.Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise ApiError("invalid_json", "بدنه‌ی درخواست نامعتبر است.")
    if not isinstance(body, dict):
        raise ApiError("invalid_json", "بدنه‌ی درخواست نامعتبر است.")
    return body


# ─────────────────────────── Handlers ───────────────────────────
async def health(request):
    return web.json_response({"ok": True})


async def auth_telegram(request: web.Request):
    body = await _json(request)
    user = auth.validate_init_data(str(body.get("init_data", "")), BOT_TOKEN, settings.INITDATA_MAX_AGE)
    uid = user["id"]
    if not await db.user_exists(uid):
        raise ApiError("not_registered", "ابتدا در ربات /start بزن و بعد Mini App را باز کن.", 403)
    bot = request.app["bot"]
    if bot is not None:
        from .bot_hooks import check_membership
        if not await check_membership(bot, uid):
            raise ApiError("membership_required", f"برای استفاده باید عضو کانال {FORCE_JOIN_CHANNEL} باشی.", 403)
    token = auth.issue_token(uid)
    await store.log_event(uid, "login", "")
    return ok({"token": token, "expires_in": settings.SESSION_TTL, "user": {"id": uid}})


async def logout(request):
    await store.revoke_sessions(request["uid"])
    return ok({"revoked": True})


async def me(request):
    return ok(await service.account(request["uid"], request.app["bot_username"]))


async def dashboard(request):
    return ok(await service.dashboard(request["uid"]))


async def plans(request):
    t = request.query.get("type")
    if t and t not in catalog.SERVICE_TYPES:
        raise ApiError("invalid_service_type", "نوع سرویس نامعتبر است.")
    return ok({"plans": catalog.list_plans(t),
               "types": [{"id": k, **catalog.TYPE_META[k], "protocols": catalog.PROTOCOLS[k]}
                         for k in catalog.SERVICE_TYPES]})


async def services_list(request):
    limit, offset = _page(request)
    return ok(await service.list_services(request["uid"], request.query.get("usage") == "1", limit, offset))


async def service_get(request):
    return ok(await service.get_service(request["uid"], _int(request, "id")))


async def service_usage(request):
    return ok(await service.get_usage(request["uid"], _int(request, "id"), force=request.query.get("fresh") == "1"))


async def service_config(request):
    return ok(await service.get_config(request["uid"], _int(request, "id")))


async def service_renew_plans(request):
    return ok(await service.renewable_plans(request["uid"], _int(request, "id")))


async def service_renew(request):
    body = await _json(request)
    body.update(kind="renew", service_id=_int(request, "id"))
    return ok(await service.create_order(request["uid"], body, request.headers.get("Idempotency-Key")), 201)


async def quote(request):
    return ok(await service.quote(request["uid"], await _json(request)))


async def orders_create(request):
    body = await _json(request)
    return ok(await service.create_order(request["uid"], body, request.headers.get("Idempotency-Key")), 201)


async def orders_list(request):
    limit, offset = _page(request)
    return ok({"items": await service.list_orders(request["uid"], limit, offset)})


async def order_get(request):
    return ok(await service.get_order(request["uid"], request.match_info["id"]))


async def order_pay(request: web.Request):
    oid = request.match_info["id"]
    if request.content_type.startswith("multipart/"):
        form = await request.post()
        method = str(form.get("method", ""))
        f = form.get("receipt")
        receipt = f.file.read(settings.MAX_RECEIPT_BYTES + 1) if f is not None and hasattr(f, "file") else None
    else:
        method, receipt = str((await _json(request)).get("method", "")), None
    return ok(await service.pay_order(request["uid"], oid, method, receipt))


async def transactions(request):
    limit, offset = _page(request)
    return ok({"items": await service.list_orders(request["uid"], limit, offset, paid_only=True)})


async def tickets_create(request):
    b = await _json(request)
    return ok(await service.create_ticket(request["uid"], b.get("category", ""), b.get("subject", ""), b.get("body", "")), 201)


async def tickets_list(request):
    limit, offset = _page(request)
    return ok({"items": await service.list_tickets(request["uid"], limit, offset),
               "categories": service.TICKET_CATEGORIES, "support_url": settings.SUPPORT_URL})


async def ticket_get(request):
    return ok(await service.get_ticket(request["uid"], _int(request, "id")))


async def ticket_reply(request):
    return ok(await service.reply_ticket(request["uid"], _int(request, "id"), (await _json(request)).get("body", "")))


async def ticket_close(request):
    if not await store.close_ticket(_int(request, "id"), request["uid"]):
        raise ApiError("not_found", "تیکت پیدا نشد.", 404)
    return ok({"closed": True})


async def index(request):
    return web.FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


def build_app(bot=None, bot_username: Optional[str] = None) -> web.Application:
    app = web.Application(middlewares=[security_headers, errors, authenticate],
                          client_max_size=settings.MAX_RECEIPT_BYTES + 512 * 1024)
    app["bot"], app["bot_username"] = bot, bot_username
    p = "/api/v1"
    app.add_routes([
        web.get("/health", health),
        web.post(f"{p}/auth/telegram", auth_telegram),
        web.post(f"{p}/auth/logout", logout),
        web.get(f"{p}/me", me),
        web.get(f"{p}/dashboard", dashboard),
        web.get(f"{p}/plans", plans),
        web.get(f"{p}/services", services_list),
        web.get(f"{p}/services/{{id}}", service_get),
        web.get(f"{p}/services/{{id}}/usage", service_usage),
        web.post(f"{p}/services/{{id}}/config", service_config),
        web.get(f"{p}/services/{{id}}/renew-plans", service_renew_plans),
        web.post(f"{p}/services/{{id}}/renew", service_renew),
        web.post(f"{p}/quote", quote),
        web.post(f"{p}/orders", orders_create),
        web.get(f"{p}/orders", orders_list),
        web.get(f"{p}/orders/{{id}}", order_get),
        web.post(f"{p}/orders/{{id}}/payment", order_pay),
        web.get(f"{p}/transactions", transactions),
        web.post(f"{p}/support/tickets", tickets_create),
        web.get(f"{p}/support/tickets", tickets_list),
        web.get(f"{p}/support/tickets/{{id}}", ticket_get),
        web.post(f"{p}/support/tickets/{{id}}/messages", ticket_reply),
        web.post(f"{p}/support/tickets/{{id}}/close", ticket_close),
        web.get("/", index),
        web.static("/static", STATIC_DIR, follow_symlinks=False),
    ])
    return app


async def start_server(bot=None, bot_username: Optional[str] = None) -> web.AppRunner:
    runner = web.AppRunner(build_app(bot, bot_username), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, settings.HOST, settings.PORT).start()
    logger.info("Mini App server listening on %s:%s", settings.HOST, settings.PORT)
    return runner
