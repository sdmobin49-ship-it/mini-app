"""
منطق تجاری Mini App: سفارش، پرداخت، فعال‌سازی قابل بازیابی، تمدید، مصرف، تیکت.

اصول:
- قیمت همیشه سمت سرور از catalog محاسبه و در سفارش «فریز» می‌شود (قیمت کلاینت نادیده گرفته می‌شود).
- سفارش (wa_orders) از سرویس (services) جدا است؛ وضعیت پرداخت از وضعیت فعال‌سازی جدا است.
- فعال‌سازی idempotent است: یوزرنیم پنل از قبل در سفارش ذخیره می‌شود و پیش از ساخت، وجودش در پنل چک می‌شود؛
  تمدید با «انقضای مطلق هدف» انجام می‌شود تا تکرار، دوبار تمدید نکند.
"""
import asyncio
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import database as db
from config import ADMIN_IDS, CARD_NUMBER, CARD_OWNER
from core_helpers import apply_discount, get_discount_for_user

from . import catalog, panel, settings, store

logger = logging.getLogger(__name__)

IDEM_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
TICKET_CATEGORIES = {
    "connection": "مشکل اتصال",
    "payment": "پرداخت و سفارش",
    "activation": "فعال‌سازی سرویس",
    "renewal": "تمدید",
    "other": "سایر",
}
MIN_TOPUP, MAX_TOPUP = 10_000, 50_000_000


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


class _NoopNotifier:
    async def user(self, user_id: int, text: str) -> None: ...
    async def admins_alert(self, text: str, order_id: Optional[int] = None) -> None: ...
    async def admins_receipt(self, order: Dict[str, Any], image: bytes, caption: str) -> Optional[str]:
        return None
    async def admins_ticket(self, ticket: Dict[str, Any], body: str) -> None: ...


notifier: Any = _NoopNotifier()
_usage_mem: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_tasks: set = set()


def _spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


# ═════════════════════════ قیمت‌گذاری و سفارش ═════════════════════════
async def _resolve_target(user_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    kind = body.get("kind")
    if kind == "topup":
        try:
            amount = int(body.get("amount"))
        except (TypeError, ValueError):
            raise ApiError("invalid_amount", "مبلغ نامعتبر است.")
        if not (MIN_TOPUP <= amount <= MAX_TOPUP):
            raise ApiError("invalid_amount", f"مبلغ شارژ باید بین {MIN_TOPUP:,} و {MAX_TOPUP:,} تومان باشد.")
        return {"kind": "topup", "base_price": amount}
    if kind == "purchase":
        stype, plan_id = body.get("service_type"), body.get("plan_id")
        if stype not in catalog.SERVICE_TYPES:
            raise ApiError("invalid_service_type", "نوع سرویس نامعتبر است.")
        plan = catalog.get_plan(stype, str(plan_id))
        if not plan:
            raise ApiError("plan_not_found", "این پلن دیگر موجود نیست.", 404)
        return {"kind": "purchase", "service_type": stype, "plan_id": str(plan_id), "base_price": int(plan["price"])}
    if kind == "renew":
        try:
            sid = int(body.get("service_id"))
        except (TypeError, ValueError):
            raise ApiError("invalid_service", "سرویس نامعتبر است.")
        row = await store.get_service_row(user_id, sid)       # فیلتر مالک → جلوگیری از IDOR
        if not row:
            raise ApiError("not_found", "سرویس پیدا نشد.", 404)
        stype = panel.resolve_type(row["panel_username"], row["service_type"])
        plan_id = str(body.get("plan_id"))
        plan = catalog.get_plan(stype, plan_id)
        if not plan:
            raise ApiError("plan_not_found", "این پلن تمدید دیگر موجود نیست.", 404)
        return {"kind": "renew", "service_type": stype, "plan_id": plan_id, "panel_username": row["panel_username"],
                "base_price": int(plan["price"])}
    raise ApiError("invalid_kind", "نوع سفارش نامعتبر است.")


async def quote(user_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    t = await _resolve_target(user_id, body)
    code = (body.get("discount_code") or "").strip() or None
    percent, discount_code = 0, None
    if code:
        if t["kind"] == "topup":
            raise ApiError("discount_not_allowed", "کد تخفیف برای شارژ کیف پول قابل استفاده نیست.")
        ok, msg, percent = await get_discount_for_user(code, user_id)
        if not ok:
            raise ApiError("discount_invalid", msg.replace("❌", "").strip(), 422)
        discount_code = code.upper()
    amount = apply_discount(t["base_price"], percent) if percent else t["base_price"]
    return {**t, "discount_code": discount_code, "discount_percent": percent, "amount": amount}


async def create_order(user_id: int, body: Dict[str, Any], idem_key: Optional[str]) -> Dict[str, Any]:
    if not idem_key or not IDEM_RE.match(idem_key):
        raise ApiError("idempotency_key_required", "کلید یکتای درخواست لازم است.")
    q = await quote(user_id, body)
    username = panel.new_username(q["service_type"]) if q["kind"] == "purchase" else q.get("panel_username")
    order = await store.create_order(
        public_id=uuid.uuid4().hex, user_id=user_id, kind=q["kind"], service_type=q.get("service_type"),
        plan_id=q.get("plan_id"), panel_username=username, base_price=q["base_price"],
        discount_code=q["discount_code"] if "discount_code" in q else None,
        discount_percent=q["discount_percent"], amount=q["amount"], idem_key=idem_key)
    await store.log_event(user_id, "order_created", f"{order['public_id']} {order['kind']} {order['amount']}")
    return await serialize_order(order)


async def serialize_order(o: Dict[str, Any], include_username: bool = True) -> Dict[str, Any]:
    plan_name = None
    if o.get("service_type") and o.get("plan_id"):
        plan_name = catalog.plan_label(o["service_type"], o["plan_id"])
    d = {
        "id": o["public_id"], "kind": o["kind"], "service_type": o.get("service_type"), "plan_id": o.get("plan_id"),
        "plan_name": plan_name, "base_price": o["base_price"], "discount_code": o.get("discount_code"),
        "discount_percent": o.get("discount_percent") or 0, "amount": o["amount"],
        "payment_method": o.get("payment_method"), "payment_status": o["payment_status"], "status": o["status"],
        "provision_attempts": o["provision_attempts"], "created_at": o["created_at"], "paid_at": o.get("paid_at"),
        "completed_at": o.get("completed_at"),
        # خطای خام پنل را به کاربر نشان نمی‌دهیم
        "error": "فعال‌سازی با تأخیر مواجه شده؛ سیستم خودکار دوباره تلاش می‌کند." if o["status"] == "failed" else None,
    }
    if o["status"] == "pending_payment":
        d["card"] = {"number": CARD_NUMBER, "owner": CARD_OWNER}
    if o["kind"] in ("purchase", "renew") and o.get("panel_username") and o["status"] == "completed":
        row = await _service_for_username(o["user_id"], o["panel_username"])
        d["service_id"] = row["id"] if row else None
    return d


async def _service_for_username(user_id: int, panel_username: str) -> Optional[Dict[str, Any]]:
    return await store.service_by_panel_username(user_id, panel_username)


async def get_order(user_id: int, public_id: str) -> Dict[str, Any]:
    o = await store.get_order(public_id, user_id)
    if not o:
        raise ApiError("not_found", "سفارش پیدا نشد.", 404)
    return await serialize_order(o)


# ═════════════════════════ پرداخت ═════════════════════════
def _image_ok(data: bytes) -> bool:
    return (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


async def pay_order(user_id: int, public_id: str, method: str, receipt: Optional[bytes] = None) -> Dict[str, Any]:
    o = await store.get_order(public_id, user_id)
    if not o:
        raise ApiError("not_found", "سفارش پیدا نشد.", 404)
    if method not in ("balance", "card"):
        raise ApiError("invalid_method", "روش پرداخت نامعتبر است.")

    if o["status"] != "pending_payment" or o["payment_status"] not in ("unpaid", "awaiting_review"):
        # کلیک دوباره/درخواست تکراری: وضعیت فعلی را برگردان، نه خطا و نه پرداخت دوباره
        if o["status"] in ("paid", "provisioning", "completed", "failed", "refunded") and \
                (o.get("payment_method") == method):
            return await serialize_order(o)
        raise ApiError("order_not_payable", "این سفارش قابل پرداخت نیست.", 409)

    if method == "balance":
        if o["kind"] == "topup":
            raise ApiError("invalid_method", "شارژ کیف پول فقط با کارت‌به‌کارت ممکن است.")
        if o["payment_status"] != "unpaid":
            raise ApiError("order_not_payable", "این سفارش در انتظار تأیید رسید است.", 409)
        if o.get("discount_code"):
            ok, msg, _ = await get_discount_for_user(o["discount_code"], user_id)
            if not ok:
                raise ApiError("discount_invalid", msg.replace("❌", "").strip(), 422)
        res = await store.pay_with_balance(o["id"], user_id)
        if res == "insufficient":
            raise ApiError("insufficient_balance", "موجودی کیف پول کافی نیست.", 402)
        if res != "ok":
            fresh = await store.get_order(public_id, user_id)
            return await serialize_order(fresh)
        if o.get("discount_code"):
            await db.record_discount_usage(o["discount_code"], user_id)
        await store.log_event(user_id, "order_paid_balance", f"{public_id} {o['amount']}")
        await _provision_and_wait(o["id"], wait=8.0)
        return await serialize_order(await store.get_order(public_id, user_id))

    # ── card: رسید داخل خود Mini App آپلود می‌شود ──
    if not receipt or not _image_ok(receipt):
        raise ApiError("invalid_receipt", "تصویر رسید معتبر نیست (JPEG/PNG/WEBP).", 422)
    if len(receipt) > settings.MAX_RECEIPT_BYTES:
        raise ApiError("receipt_too_large", "حجم تصویر رسید باید کمتر از ۵ مگابایت باشد.", 413)
    if o["payment_status"] == "awaiting_review":
        raise ApiError("already_submitted", "رسید این سفارش قبلاً ارسال شده و در انتظار تأیید است.", 409)
    if not await store.submit_receipt(o["id"], user_id, None):     # گارد کلیک دوباره
        raise ApiError("already_submitted", "رسید این سفارش قبلاً ارسال شده است.", 409)
    user = await store.get_user_row(user_id) or {}
    o = await store.get_order(public_id, user_id)
    caption = _receipt_caption(o, user)
    file_id = await notifier.admins_receipt(o, receipt, caption)
    if file_id is None:
        await store.unsubmit_receipt(o["id"])
        raise ApiError("admin_unreachable", "ارسال رسید برای ادمین ممکن نشد؛ کمی بعد دوباره تلاش کن.", 503)
    await store.update_order_fields(o["id"], receipt_file_id=file_id)
    await store.log_event(user_id, "receipt_submitted", public_id)
    return await serialize_order(await store.get_order(public_id, user_id))


def _receipt_caption(o: Dict[str, Any], user: Dict[str, Any]) -> str:
    kinds = {"purchase": "🛒 خرید سرویس (Mini App)", "renew": "🔄 تمدید سرویس (Mini App)",
             "topup": "💳 شارژ کیف پول (Mini App)"}
    lines = [f"<b>{kinds[o['kind']]}</b>", "",
             f"👤 کاربر: <code>{o['user_id']}</code> {user.get('full_name') or ''}".rstrip(),
             f"💰 مبلغ: <b>{o['amount']:,} تومان</b>"]
    if o.get("service_type"):
        lines.append(f"📦 پلن: {catalog.plan_label(o['service_type'], o['plan_id'])} ({o['service_type']})")
    if o["kind"] == "renew":
        lines.append(f"🔑 سرویس: <code>{o['panel_username']}</code>")
    if o.get("discount_code"):
        lines.append(f"🏷 کد تخفیف: {o['discount_code']} ({o['discount_percent']}٪)")
    lines.append(f"🧾 سفارش: <code>{o['public_id'][:12]}</code>")
    return "\n".join(lines)


async def approve_order(order_id: int, admin_id: int) -> str:
    """تأیید پرداخت توسط ادمین. خروجی: 'approved' | 'already_processed'."""
    o = await store.get_order_by_id(order_id)
    if not o:
        return "already_processed"
    if not await store.mark_paid_by_admin(order_id):
        return "already_processed"
    if o.get("discount_code"):
        await db.record_discount_usage(o["discount_code"], o["user_id"])
    await store.log_event(o["user_id"], "order_approved", f"{o['public_id']} by {admin_id}")
    await notifier.user(o["user_id"], "✅ پرداخت شما تأیید شد؛ در حال فعال‌سازی هستیم…")
    _spawn(provision(order_id))
    return "approved"


async def reject_order(order_id: int, admin_id: int) -> str:
    o = await store.get_order_by_id(order_id)
    if not o or not await store.reject_order(order_id):
        return "already_processed"
    await store.log_event(o["user_id"], "order_rejected", f"{o['public_id']} by {admin_id}")
    await notifier.user(o["user_id"], "❌ رسید پرداخت شما تأیید نشد. در صورت اشتباه با پشتیبانی تماس بگیرید.")
    return "rejected"


# ═════════════════════════ فعال‌سازی (قابل بازیابی) ═════════════════════════
def _sanitize(e: Exception) -> str:
    s = f"{type(e).__name__}: {e}"
    return re.sub(r"(Bearer\s+\S+|password\S*\s*[=:]\s*\S+|token\S*\s*[=:]\s*\S+)", "<hidden>", s, flags=re.I)[:300]


async def _provision_and_wait(order_id: int, wait: float) -> None:
    task = _spawn(provision(order_id))
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=wait)
    except asyncio.TimeoutError:
        pass            # کاربر پیام «در حال فعال‌سازی» می‌بیند؛ کار در پس‌زمینه ادامه دارد
    except Exception:
        logger.exception("provision task error")


async def provision(order_id: int) -> Optional[str]:
    o = await store.claim_provisioning(order_id, settings.PROVISION_LOCK_SECONDS)
    if not o:
        return None
    try:
        if o["kind"] == "purchase":
            await _do_purchase(o)
        elif o["kind"] == "renew":
            await _do_renew(o)
        else:
            if not await store.complete_topup(o["id"]):
                raise RuntimeError("topup_state_conflict")
        if o["kind"] != "topup" and not await store.complete_order(o["id"]):
            raise RuntimeError("order_state_conflict")
    except Exception as e:
        err = _sanitize(e)
        logger.error("provision failed order=%s attempt=%s: %s", o["public_id"], o["provision_attempts"], err)
        attempts = o["provision_attempts"]
        if attempts >= settings.MAX_PROVISION_ATTEMPTS:
            await store.fail_order(o["id"], err, None)
            await _permanent_failure(o, err)
            return "failed_permanent"
        delay = settings.RETRY_BACKOFF[min(attempts - 1, len(settings.RETRY_BACKOFF) - 1)]
        await store.fail_order(o["id"], err, store.now() + delay)
        if attempts == 1:
            await notifier.user(o["user_id"], "⏳ فعال‌سازی سرویس شما کمی طول کشیده؛ خودکار ادامه پیدا می‌کند.")
        return "failed_retry"
    await store.log_event(o["user_id"], "order_completed", o["public_id"])
    await notifier.user(o["user_id"], _done_text(o))
    return "completed"


def _done_text(o: Dict[str, Any]) -> str:
    return {"purchase": "✅ سرویس شما فعال شد! از بخش «سرویس‌های من» در Mini App کانفیگ را بگیر.",
            "renew": "✅ سرویس شما تمدید شد.",
            "topup": f"✅ کیف پول شما {o['amount']:,} تومان شارژ شد."}[o["kind"]]


async def _permanent_failure(o: Dict[str, Any], err: str) -> None:
    if o.get("payment_method") == "balance" and await store.refund_to_balance(o["id"]):
        await notifier.user(o["user_id"], "❌ فعال‌سازی ممکن نشد و مبلغ به کیف پولت برگشت داده شد.")
        await notifier.admins_alert(f"⚠️ سفارش {o['public_id'][:12]} پس از چند تلاش ناموفق ماند و به کیف پول برگشت.\n{err}")
        return
    await notifier.admins_alert(
        f"🚨 فعال‌سازی سفارش <code>{o['public_id'][:12]}</code> (کاربر <code>{o['user_id']}</code>, "
        f"{o['kind']}, {o['amount']:,} تومان) پس از {o['provision_attempts']} تلاش ناموفق ماند.\n{err}", o["id"])
    await notifier.user(o["user_id"], "⚠️ فعال‌سازی سرویس با مشکل مواجه شد؛ پشتیبانی بررسی می‌کند و اطلاع می‌دهد.")


async def _do_purchase(o: Dict[str, Any]) -> None:
    stype, username = o["service_type"], o["panel_username"]
    plan = catalog.get_plan(stype, o["plan_id"])
    if not plan:       # پلن بعد از پرداخت از config حذف شده؛ با قیمت/مشخصات ثبت‌شده‌ی سفارش نمی‌توان ساخت
        raise RuntimeError("plan_removed_from_catalog")
    ud = await panel.fetch_user(stype, username)       # idempotency: اگر قبلاً ساخته شده، همان را بپذیر
    if not ud:
        ud = await panel.create_user(stype, username, plan)
    if not ud:
        raise RuntimeError("panel_create_failed")        # پاسخ ناموفق/نامعتبر پنل → تلاش مجدد
    await store.save_service_if_absent(o["user_id"], username, o["plan_id"], ud.get("subscription_url", "") or "", stype)


async def _do_renew(o: Dict[str, Any]) -> None:
    stype, username = o["service_type"], o["panel_username"]
    plan = catalog.get_plan(stype, o["plan_id"])
    if not plan:
        raise RuntimeError("plan_removed_from_catalog")
    target = o.get("target_expire")
    if target is None:
        ud = await panel.fetch_user(stype, username)
        if not ud:
            raise RuntimeError("service_not_found_on_panel")
        cur = panel.normalize(ud)["expire_ts"] or 0
        target = max(cur, int(time.time())) + plan["duration_days"] * 86400
        await store.update_order_fields(o["id"], target_expire=target)     # قبل از دست‌زدن به پنل ذخیره می‌شود
    volume = stype in ("cdn", "tunnel")
    if volume and o.get("step") != "reset_done":
        if not await panel.reset_traffic(stype, username):
            raise RuntimeError("panel_reset_failed")
        await store.update_order_fields(o["id"], step="reset_done")
    res = await panel.set_limits(stype, username, target, plan["data_limit_gb"] if volume else None)
    if not res:
        raise RuntimeError("panel_update_failed")
    _usage_mem.pop(username, None)
    await store.drop_usage_cache(username)


async def run_retry_worker(stop: asyncio.Event) -> None:
    """هر چند ثانیه سفارش‌های paid/failed(رسیده)/provisioning کهنه را دوباره پردازش می‌کند."""
    while not stop.is_set():
        try:
            for oid in await store.due_order_ids(settings.PROVISION_LOCK_SECONDS):
                await provision(oid)
        except Exception:
            logger.exception("retry worker error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.WORKER_INTERVAL)
        except asyncio.TimeoutError:
            pass


# ═════════════════════════ سرویس‌ها و مصرف ═════════════════════════
async def usage_for(row: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    uname = row["panel_username"]
    stype = panel.resolve_type(uname, row["service_type"])
    t = time.time()
    hit = _usage_mem.get(uname)
    if hit and not force and t - hit[0] < settings.USAGE_TTL:
        return {**hit[1], "stale": False}
    ud = None
    try:
        ud = await asyncio.wait_for(panel.fetch_user(stype, uname), timeout=8)
    except Exception as e:
        logger.warning("usage fetch failed for %s: %s", uname, _sanitize(e))
    if ud:
        payload = {"available": True, **panel.normalize(ud), "fetched_at": int(t)}
        _usage_mem[uname] = (t, payload)
        await store.set_usage_cache(uname, {k: v for k, v in payload.items() if k != "fetched_at"})
        return {**payload, "stale": False}
    saved = await store.get_usage_cache(uname)       # آخرین اطلاعات ذخیره‌شده با زمان به‌روزرسانی
    if saved:
        return {"available": True, **saved, "stale": True}
    return {"available": False, "stale": True, "fetched_at": None, "status": "unknown", "used_bytes": None,
            "limit_bytes": None, "remaining_bytes": None, "expire_ts": None, "days_left": None, "protocols": []}


def _service_view(row: Dict[str, Any], usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    stype = panel.resolve_type(row["panel_username"], row["service_type"])
    return {
        "id": row["id"], "panel_username": row["panel_username"], "service_type": stype,
        "kind": catalog.TYPE_META[stype]["kind"], "type_title": catalog.TYPE_META[stype]["title"],
        "plan_id": row["plan_id"], "plan_name": catalog.plan_label(stype, row["plan_id"] or ""),
        "created_at": row["created_at"], "usage": usage,
    }


async def _usages(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sem = asyncio.Semaphore(5)

    async def one(r):
        async with sem:
            return await usage_for(r)
    return await asyncio.gather(*[one(r) for r in rows])


async def list_services(user_id: int, with_usage: bool, limit: int, offset: int) -> Dict[str, Any]:
    rows = await store.list_service_rows(user_id)
    page = rows[offset:offset + limit]
    usages = await _usages(page) if with_usage else [None] * len(page)
    return {"items": [_service_view(r, u) for r, u in zip(page, usages)], "total": len(rows),
            "limit": limit, "offset": offset}


async def get_service(user_id: int, service_id: int) -> Dict[str, Any]:
    row = await store.get_service_row(user_id, service_id)
    if not row:
        raise ApiError("not_found", "سرویس پیدا نشد.", 404)
    return _service_view(row, await usage_for(row))


async def get_usage(user_id: int, service_id: int, force: bool = False) -> Dict[str, Any]:
    row = await store.get_service_row(user_id, service_id)
    if not row:
        raise ApiError("not_found", "سرویس پیدا نشد.", 404)
    return await usage_for(row, force=force)


async def get_config(user_id: int, service_id: int) -> Dict[str, Any]:
    row = await store.get_service_row(user_id, service_id)
    if not row:
        raise ApiError("not_found", "سرویس پیدا نشد.", 404)
    sub, links = row.get("subscription_url") or "", []
    if not sub:
        try:
            ud = await panel.fetch_user(panel.resolve_type(row["panel_username"], row["service_type"]), row["panel_username"])
            sub = (ud or {}).get("subscription_url", "") or ""
            links = list((ud or {}).get("links") or [])
        except Exception:
            pass
    if not sub:
        raise ApiError("config_unavailable", "لینک اشتراک فعلاً در دسترس نیست.", 503)
    await store.log_event(user_id, "config_viewed", f"service={service_id}")      # خود کانفیگ هرگز لاگ نمی‌شود
    return {"subscription_url": sub, "links": links}


async def renewable_plans(user_id: int, service_id: int) -> Dict[str, Any]:
    row = await store.get_service_row(user_id, service_id)
    if not row:
        raise ApiError("not_found", "سرویس پیدا نشد.", 404)
    stype = panel.resolve_type(row["panel_username"], row["service_type"])
    return {"service_type": stype, "plans": catalog.list_plans(stype)}


# ═════════════════════════ داشبورد، حساب ═════════════════════════
async def dashboard(user_id: int) -> Dict[str, Any]:
    rows = await store.list_service_rows(user_id)
    shown = rows[:10]
    usages = await _usages(shown)
    views = [_service_view(r, u) for r, u in zip(shown, usages)]
    active = sum(1 for v in views if v["usage"] and v["usage"]["available"] and v["usage"]["status"] == "active")
    user = await store.get_user_row(user_id) or {}
    primary = next((v for v in views if v["usage"] and v["usage"]["status"] == "active"), views[0] if views else None)
    return {
        "user": {"id": user_id, "name": user.get("full_name"), "username": user.get("username")},
        "balance": await db.get_balance(user_id),
        "services_total": len(rows), "services_active": active,
        "pending_orders": await store.count_open_orders(user_id),
        "open_tickets": await store.count_open_tickets(user_id),
        "primary_service": primary,
        "alerts": _alerts(views),
    }


def _alerts(views: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for v in views:
        u = v["usage"]
        if not u or not u["available"]:
            continue
        if u["status"] in ("expired", "limited", "disabled"):
            out.append({"type": u["status"], "service_id": v["id"]})
        elif u["days_left"] is not None and u["days_left"] <= 3:
            out.append({"type": "expiring", "service_id": v["id"], "days_left": u["days_left"]})
        elif u["limit_bytes"] and u["remaining_bytes"] is not None and u["remaining_bytes"] <= 0.1 * u["limit_bytes"]:
            out.append({"type": "low_data", "service_id": v["id"]})
    return out


async def account(user_id: int, bot_username: Optional[str]) -> Dict[str, Any]:
    user = await store.get_user_row(user_id) or {}
    pts = await db.get_referral_points(user_id)
    return {
        "user": {"id": user_id, "name": user.get("full_name"), "username": user.get("username"),
                 "joined_at": user.get("joined_at")},
        "balance": await db.get_balance(user_id),
        "referral": {"count": await db.get_referral_count(user_id), "points": pts["points"],
                     "total_earned": pts["total_earned"],
                     "link": f"https://t.me/{bot_username}?start=ref_{user_id}" if bot_username else None},
        "support_url": settings.SUPPORT_URL,
    }


async def list_orders(user_id: int, limit: int, offset: int, paid_only: bool = False) -> List[Dict[str, Any]]:
    rows = await store.list_orders(user_id, limit, offset, paid_only=paid_only)
    return [await serialize_order(o) for o in rows]


# ═════════════════════════ تیکت پشتیبانی ═════════════════════════
async def create_ticket(user_id: int, category: str, subject: str, body: str) -> Dict[str, Any]:
    subject, body = (subject or "").strip(), (body or "").strip()
    if category not in TICKET_CATEGORIES:
        raise ApiError("invalid_category", "دسته‌بندی نامعتبر است.")
    if not (3 <= len(subject) <= 100):
        raise ApiError("invalid_subject", "موضوع باید بین ۳ تا ۱۰۰ نویسه باشد.")
    if not (5 <= len(body) <= 2000):
        raise ApiError("invalid_body", "متن پیام باید بین ۵ تا ۲۰۰۰ نویسه باشد.")
    if await store.count_open_tickets(user_id) >= 5:
        raise ApiError("too_many_open_tickets", "تعداد تیکت‌های باز شما به سقف رسیده است.", 429)
    t = await store.create_ticket(user_id, category, subject, body)
    await store.log_event(user_id, "ticket_created", str(t["id"]))
    await notifier.admins_ticket(t, body)
    return await get_ticket(user_id, t["id"])


async def get_ticket(user_id: int, ticket_id: int) -> Dict[str, Any]:
    t = await store.get_ticket(ticket_id, user_id)
    if not t:
        raise ApiError("not_found", "تیکت پیدا نشد.", 404)
    t["category_title"] = TICKET_CATEGORIES.get(t["category"], t["category"])
    return t


async def reply_ticket(user_id: int, ticket_id: int, body: str) -> Dict[str, Any]:
    body = (body or "").strip()
    t = await store.get_ticket(ticket_id, user_id)
    if not t:
        raise ApiError("not_found", "تیکت پیدا نشد.", 404)
    if t["status"] == "closed":
        raise ApiError("ticket_closed", "این تیکت بسته شده است.", 409)
    if not (2 <= len(body) <= 2000):
        raise ApiError("invalid_body", "متن پیام باید بین ۲ تا ۲۰۰۰ نویسه باشد.")
    await store.add_ticket_message(ticket_id, "user", body)
    await notifier.admins_ticket(t, body)
    return await get_ticket(user_id, ticket_id)


async def list_tickets(user_id: int, limit: int, offset: int) -> List[Dict[str, Any]]:
    items = await store.list_tickets(user_id, limit, offset)
    for t in items:
        t["category_title"] = TICKET_CATEGORIES.get(t["category"], t["category"])
    return items


async def admin_reply_ticket(ticket_id: int, body: str) -> Optional[int]:
    """پاسخ ادمین؛ user_id صاحب تیکت را برمی‌گرداند."""
    t = await store.get_ticket(ticket_id)
    if not t:
        return None
    await store.add_ticket_message(ticket_id, "admin", body)
    return t["user_id"]
