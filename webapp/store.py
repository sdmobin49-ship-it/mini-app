"""
لایه‌ی دیتابیس Mini App روی همان فایل SQLite ربات (database.DB_PATH).

- جدول‌های موجود دست‌نخورده می‌مانند؛ فقط جدول‌های wa_* به‌صورت افزایشی اضافه می‌شوند.
- عملیات پولی (کسر موجودی، تغییر وضعیت سفارش، شارژ کیف پول) اتمیک و داخل یک تراکنش‌اند.
"""
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import aiosqlite

import database as db

SCHEMA_VERSION = 1

MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS wa_orders (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            public_id        TEXT NOT NULL UNIQUE,
            user_id          INTEGER NOT NULL,
            kind             TEXT NOT NULL,              -- purchase | renew | topup
            service_type     TEXT,                       -- cdn | tunnel | unlimited
            plan_id          TEXT,
            panel_username   TEXT,                       -- خرید: از قبل ساخته می‌شود تا تلاش مجدد idempotent باشد
            base_price       INTEGER NOT NULL,
            discount_code    TEXT,
            discount_percent INTEGER DEFAULT 0,
            amount           INTEGER NOT NULL,           -- مبلغ نهایی (ثابت پس از ساخت سفارش)
            payment_method   TEXT,                       -- balance | card
            payment_status   TEXT NOT NULL DEFAULT 'unpaid',  -- unpaid | awaiting_review | paid | rejected
            status           TEXT NOT NULL DEFAULT 'pending_payment',
                             -- pending_payment | paid | provisioning | completed | failed | rejected | refunded | cancelled
            provision_attempts INTEGER NOT NULL DEFAULT 0,
            next_retry_at    INTEGER,
            last_error       TEXT,
            target_expire    INTEGER,                    -- تمدید: انقضای مطلق هدف (برای تکرار امن)
            step             TEXT,                       -- پیشرفت عملیات چندمرحله‌ای (مثلاً reset_done)
            idem_key         TEXT,
            receipt_file_id  TEXT,
            created_at       INTEGER NOT NULL,
            updated_at       INTEGER NOT NULL,
            paid_at          INTEGER,
            completed_at     INTEGER
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_wa_orders_idem ON wa_orders(user_id, idem_key) WHERE idem_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_wa_orders_user ON wa_orders(user_id, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_wa_orders_status ON wa_orders(status, next_retry_at)",
        """CREATE TABLE IF NOT EXISTS wa_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            category TEXT NOT NULL, subject TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',          -- open | answered | closed
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_wa_tickets_user ON wa_tickets(user_id, id DESC)",
        """CREATE TABLE IF NOT EXISTS wa_ticket_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL,
            sender TEXT NOT NULL,                          -- user | admin
            body TEXT NOT NULL, created_at INTEGER NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS ix_wa_ticket_msgs ON wa_ticket_messages(ticket_id, id)",
        """CREATE TABLE IF NOT EXISTS wa_usage_cache (
            panel_username TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS wa_sessions (
            user_id INTEGER PRIMARY KEY, min_iat INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS wa_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event TEXT NOT NULL,
            detail TEXT, created_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS wa_meta (key TEXT PRIMARY KEY, value TEXT)""",
    ],
}


def now() -> int:
    return int(time.time())


@asynccontextmanager
async def conn():
    # isolation_level=None → کنترل دستی تراکنش (BEGIN IMMEDIATE)
    # timeout=10 همان busy_timeout است (PRAGMA جدا لازم نیست؛ cursor باز PRAGMA یک snapshot خوانش نگه می‌دارد
    # و در WAL باعث «database is locked» آنی در BEGIN IMMEDIATE می‌شد)
    async with aiosqlite.connect(db.DB_PATH, isolation_level=None, timeout=10) as c:
        c.row_factory = aiosqlite.Row
        yield c


async def migrate() -> None:
    """ایجاد جدول‌های قدیمی (idempotent) و اعمال Migration افزایشی."""
    await db.init_db()
    async with conn() as c:
        # پیش‌فرض: حالت journal عادی (DELETE) تا فایل vpn_bot.db همیشه «تک‌فایل و کامل» باشد و با دانلود/آپلود دستی
        # (مثل روش قبلی) داده‌ای در فایل‌های -wal/-shm جا نماند. فقط با DB_WAL=1 حالت WAL فعال می‌شود.
        mode = "WAL" if os.getenv("DB_WAL") == "1" else "DELETE"
        try:
            cur = await c.execute(f"PRAGMA journal_mode={mode}")
            await cur.fetchall()                  # cursor را کامل می‌بندیم تا snapshot باز نماند
        except Exception:                         # تغییر حالت شکست بخورد (مثلاً اتصال دیگری باز است) ربات نباید کرش کند
            logging.getLogger(__name__).warning("could not switch journal_mode to %s", mode)
        await c.execute("CREATE TABLE IF NOT EXISTS wa_meta (key TEXT PRIMARY KEY, value TEXT)")
        cur = await c.execute("SELECT value FROM wa_meta WHERE key='schema_version'")
        row = await cur.fetchone()
        current = int(row[0]) if row else 0
        for v in range(current + 1, SCHEMA_VERSION + 1):
            await c.execute("BEGIN IMMEDIATE")
            try:
                for stmt in MIGRATIONS[v]:
                    await c.execute(stmt)
                await c.execute("INSERT INTO wa_meta(key,value) VALUES('schema_version',?) "
                                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(v),))
                await c.execute("COMMIT")
            except Exception:
                await c.execute("ROLLBACK")
                raise


async def log_event(user_id: Optional[int], event: str, detail: str = "") -> None:
    async with conn() as c:
        await c.execute("INSERT INTO wa_events(user_id,event,detail,created_at) VALUES(?,?,?,?)",
                        (user_id, event, detail[:500], now()))


# ── Sessions ─────────────────────────────────────────────────────
async def get_min_iat(user_id: int) -> int:
    async with conn() as c:
        cur = await c.execute("SELECT min_iat FROM wa_sessions WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def revoke_sessions(user_id: int) -> None:
    async with conn() as c:
        await c.execute("INSERT INTO wa_sessions(user_id,min_iat) VALUES(?,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET min_iat=excluded.min_iat", (user_id, now() + 1))


# ── Orders ───────────────────────────────────────────────────────
def _row(r) -> Optional[Dict[str, Any]]:
    return dict(r) if r is not None else None


async def create_order(**f) -> Dict[str, Any]:
    """درج سفارش؛ اگر (user_id, idem_key) تکراری باشد همان سفارش قبلی برگردانده می‌شود."""
    t = now()
    cols = ["public_id", "user_id", "kind", "service_type", "plan_id", "panel_username", "base_price",
            "discount_code", "discount_percent", "amount", "idem_key", "created_at", "updated_at"]
    vals = [f["public_id"], f["user_id"], f["kind"], f.get("service_type"), f.get("plan_id"),
            f.get("panel_username"), f["base_price"], f.get("discount_code"), f.get("discount_percent", 0),
            f["amount"], f.get("idem_key"), t, t]
    async with conn() as c:
        try:
            await c.execute(f"INSERT INTO wa_orders({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
        except aiosqlite.IntegrityError:
            if not f.get("idem_key"):
                raise
            cur = await c.execute("SELECT * FROM wa_orders WHERE user_id=? AND idem_key=?",
                                  (f["user_id"], f["idem_key"]))
            return _row(await cur.fetchone())
        cur = await c.execute("SELECT * FROM wa_orders WHERE public_id=?", (f["public_id"],))
        return _row(await cur.fetchone())


async def get_order(public_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """اگر user_id داده شود، فقط سفارش همان کاربر برمی‌گردد (جلوگیری از IDOR)."""
    q, args = "SELECT * FROM wa_orders WHERE public_id=?", [public_id]
    if user_id is not None:
        q += " AND user_id=?"
        args.append(user_id)
    async with conn() as c:
        cur = await c.execute(q, args)
        return _row(await cur.fetchone())


async def get_order_by_id(order_id: int) -> Optional[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute("SELECT * FROM wa_orders WHERE id=?", (order_id,))
        return _row(await cur.fetchone())


async def list_orders(user_id: int, limit: int, offset: int, kinds: Optional[List[str]] = None,
                      paid_only: bool = False) -> List[Dict[str, Any]]:
    q, args = "SELECT * FROM wa_orders WHERE user_id=?", [user_id]
    if kinds:
        q += f" AND kind IN ({','.join('?' * len(kinds))})"
        args += kinds
    if paid_only:
        q += " AND payment_status='paid'"
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    async with conn() as c:
        cur = await c.execute(q, args)
        return [dict(r) for r in await cur.fetchall()]


async def count_open_orders(user_id: int) -> int:
    """سفارش‌های در انتظار: Mini App + درخواست‌های رسید ربات (pending_purchases)."""
    async with conn() as c:
        cur = await c.execute(
            "SELECT COUNT(*) FROM wa_orders WHERE user_id=? AND status IN "
            "('paid','provisioning','failed') OR (user_id=? AND status='pending_payment' AND payment_status='awaiting_review')",
            (user_id, user_id))
        n = (await cur.fetchone())[0]
        cur = await c.execute("SELECT COUNT(*) FROM pending_purchases WHERE user_id=?", (user_id,))
        return n + (await cur.fetchone())[0]


async def pay_with_balance(order_id: int, user_id: int) -> str:
    """
    پرداخت اتمیک از موجودی: سفارش pending_payment→paid و کسر موجودی در یک تراکنش.
    خروجی: 'ok' | 'not_payable' | 'insufficient'
    """
    t = now()
    async with conn() as c:
        await c.execute("BEGIN IMMEDIATE")
        try:
            cur = await c.execute(
                "UPDATE wa_orders SET status='paid', payment_method='balance', payment_status='paid', "
                "paid_at=?, updated_at=? WHERE id=? AND user_id=? AND status='pending_payment' "
                "AND payment_status='unpaid' AND kind!='topup'", (t, t, order_id, user_id))
            if cur.rowcount != 1:
                await c.execute("ROLLBACK")
                return "not_payable"
            cur = await c.execute(
                "UPDATE balance SET amount = amount - (SELECT amount FROM wa_orders WHERE id=?) "
                "WHERE user_id=? AND amount >= (SELECT amount FROM wa_orders WHERE id=?)",
                (order_id, user_id, order_id))
            if cur.rowcount != 1:
                await c.execute("ROLLBACK")
                return "insufficient"
            await c.execute("COMMIT")
            return "ok"
        except Exception:
            await c.execute("ROLLBACK")
            raise


async def submit_receipt(order_id: int, user_id: int, file_id: Optional[str]) -> bool:
    t = now()
    async with conn() as c:
        cur = await c.execute(
            "UPDATE wa_orders SET payment_method='card', payment_status='awaiting_review', "
            "receipt_file_id=COALESCE(?, receipt_file_id), updated_at=? "
            "WHERE id=? AND user_id=? AND status='pending_payment' AND payment_status IN ('unpaid','awaiting_review')",
            (file_id, t, order_id, user_id))
        return cur.rowcount == 1


async def mark_paid_by_admin(order_id: int) -> bool:
    t = now()
    async with conn() as c:
        cur = await c.execute(
            "UPDATE wa_orders SET status='paid', payment_status='paid', payment_method=COALESCE(payment_method,'card'), "
            "paid_at=?, updated_at=? WHERE id=? AND status='pending_payment' "
            "AND payment_status IN ('unpaid','awaiting_review')", (t, t, order_id))
        return cur.rowcount == 1


async def reject_order(order_id: int) -> bool:
    t = now()
    async with conn() as c:
        cur = await c.execute(
            "UPDATE wa_orders SET status='rejected', payment_status='rejected', updated_at=? "
            "WHERE id=? AND status='pending_payment'", (t, order_id))
        return cur.rowcount == 1


async def claim_provisioning(order_id: int, lock_seconds: int) -> Optional[Dict[str, Any]]:
    """
    فقط یک worker/درخواست می‌تواند سفارش را claim کند:
    paid → provisioning، یا failed با next_retry_at رسیده، یا provisioning کهنه (پروسه وسط کار مرده).
    """
    t = now()
    async with conn() as c:
        cur = await c.execute(
            "UPDATE wa_orders SET status='provisioning', provision_attempts=provision_attempts+1, updated_at=? "
            "WHERE id=? AND (status='paid' "
            "OR (status='failed' AND next_retry_at IS NOT NULL AND next_retry_at<=?) "
            "OR (status='provisioning' AND updated_at<=?))", (t, order_id, t, t - lock_seconds))
        if cur.rowcount != 1:
            return None
        cur = await c.execute("SELECT * FROM wa_orders WHERE id=?", (order_id,))
        return _row(await cur.fetchone())


async def update_order_fields(order_id: int, **fields) -> None:
    allowed = {"panel_username", "target_expire", "step", "receipt_file_id"}
    assert set(fields) <= allowed
    sets = ",".join(f"{k}=?" for k in fields) + ",updated_at=?"
    async with conn() as c:
        await c.execute(f"UPDATE wa_orders SET {sets} WHERE id=?", [*fields.values(), now(), order_id])


async def complete_order(order_id: int) -> bool:
    t = now()
    async with conn() as c:
        cur = await c.execute(
            "UPDATE wa_orders SET status='completed', last_error=NULL, next_retry_at=NULL, completed_at=?, updated_at=? "
            "WHERE id=? AND status='provisioning'", (t, t, order_id))
        return cur.rowcount == 1


async def complete_topup(order_id: int) -> bool:
    """شارژ کیف پول و completed شدن سفارش در یک تراکنش → شارژ دوباره غیرممکن است."""
    t = now()
    async with conn() as c:
        await c.execute("BEGIN IMMEDIATE")
        try:
            cur = await c.execute(
                "UPDATE wa_orders SET status='completed', last_error=NULL, completed_at=?, updated_at=? "
                "WHERE id=? AND kind='topup' AND status='provisioning'", (t, t, order_id))
            if cur.rowcount != 1:
                await c.execute("ROLLBACK")
                return False
            await c.execute(
                "INSERT INTO balance(user_id, amount) SELECT user_id, amount FROM wa_orders WHERE id=? "
                "ON CONFLICT(user_id) DO UPDATE SET amount = amount + excluded.amount", (order_id,))
            await c.execute("COMMIT")
            return True
        except Exception:
            await c.execute("ROLLBACK")
            raise


async def fail_order(order_id: int, error: str, next_retry_at: Optional[int]) -> None:
    async with conn() as c:
        await c.execute(
            "UPDATE wa_orders SET status='failed', last_error=?, next_retry_at=?, updated_at=? "
            "WHERE id=? AND status='provisioning'", (error[:300], next_retry_at, now(), order_id))


async def refund_to_balance(order_id: int) -> bool:
    """بازگشت وجه پرداخت‌شده از موجودی به کیف پول (اتمیک، فقط یک‌بار)."""
    t = now()
    async with conn() as c:
        await c.execute("BEGIN IMMEDIATE")
        try:
            cur = await c.execute(
                "UPDATE wa_orders SET status='refunded', updated_at=? WHERE id=? AND payment_method='balance' "
                "AND payment_status='paid' AND status IN ('failed','provisioning','paid')", (t, order_id))
            if cur.rowcount != 1:
                await c.execute("ROLLBACK")
                return False
            await c.execute(
                "INSERT INTO balance(user_id, amount) SELECT user_id, amount FROM wa_orders WHERE id=? "
                "ON CONFLICT(user_id) DO UPDATE SET amount = amount + excluded.amount", (order_id,))
            await c.execute("COMMIT")
            return True
        except Exception:
            await c.execute("ROLLBACK")
            raise


async def reset_for_retry(order_id: int) -> bool:
    """بازگرداندن سفارش failed به paid برای تلاش دستی ادمین."""
    async with conn() as c:
        cur = await c.execute(
            "UPDATE wa_orders SET status='paid', next_retry_at=NULL, provision_attempts=0, updated_at=? "
            "WHERE id=? AND status='failed'", (now(), order_id))
        return cur.rowcount == 1


async def due_order_ids(lock_seconds: int, limit: int = 20) -> List[int]:
    t = now()
    async with conn() as c:
        cur = await c.execute(
            "SELECT id FROM wa_orders WHERE status='paid' "
            "OR (status='failed' AND next_retry_at IS NOT NULL AND next_retry_at<=?) "
            "OR (status='provisioning' AND updated_at<=?) ORDER BY id LIMIT ?", (t, t - lock_seconds, limit))
        return [r[0] for r in await cur.fetchall()]


# ── Services (جدول موجود ربات؛ همیشه با فیلتر مالک) ─────────────
async def get_service_row(user_id: int, service_id: int) -> Optional[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute(
            "SELECT id, user_id, panel_username, plan_id, service_type, subscription_url, created_at "
            "FROM services WHERE id=? AND user_id=?", (service_id, user_id))
        return _row(await cur.fetchone())


async def list_service_rows(user_id: int) -> List[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute(
            "SELECT id, user_id, panel_username, plan_id, service_type, subscription_url, created_at "
            "FROM services WHERE user_id=? ORDER BY created_at DESC, id DESC", (user_id,))
        return [dict(r) for r in await cur.fetchall()]


async def service_by_panel_username(user_id: int, panel_username: str) -> Optional[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute(
            "SELECT id, user_id, panel_username, plan_id, service_type, subscription_url, created_at "
            "FROM services WHERE panel_username=? AND user_id=?", (panel_username, user_id))
        return _row(await cur.fetchone())


async def save_service_if_absent(user_id: int, panel_username: str, plan_id: str,
                                 subscription_url: str, service_type: str) -> None:
    """ثبت سرویس بدون REPLACE (تکرار فعال‌سازی ردیف تکراری یا تغییر id نمی‌سازد)."""
    async with conn() as c:
        await c.execute(
            "INSERT INTO services(user_id,panel_username,plan_id,subscription_url,service_type) "
            "VALUES(?,?,?,?,?) ON CONFLICT(panel_username) DO UPDATE SET subscription_url=excluded.subscription_url "
            "WHERE services.user_id=excluded.user_id",
            (user_id, panel_username, plan_id, subscription_url, service_type))


# ── Usage cache ──────────────────────────────────────────────────
async def get_usage_cache(panel_username: str) -> Optional[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute("SELECT payload, fetched_at FROM wa_usage_cache WHERE panel_username=?",
                              (panel_username,))
        r = await cur.fetchone()
        if not r:
            return None
        d = json.loads(r[0])
        d["fetched_at"] = r[1]
        return d


async def set_usage_cache(panel_username: str, payload: Dict[str, Any]) -> None:
    async with conn() as c:
        await c.execute("INSERT INTO wa_usage_cache(panel_username,payload,fetched_at) VALUES(?,?,?) "
                        "ON CONFLICT(panel_username) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at",
                        (panel_username, json.dumps(payload), now()))


# ── Tickets ──────────────────────────────────────────────────────
async def create_ticket(user_id: int, category: str, subject: str, body: str) -> Dict[str, Any]:
    t = now()
    async with conn() as c:
        cur = await c.execute("INSERT INTO wa_tickets(user_id,category,subject,created_at,updated_at) VALUES(?,?,?,?,?)",
                              (user_id, category, subject, t, t))
        tid = cur.lastrowid
        await c.execute("INSERT INTO wa_ticket_messages(ticket_id,sender,body,created_at) VALUES(?,?,?,?)",
                        (tid, "user", body, t))
        cur = await c.execute("SELECT * FROM wa_tickets WHERE id=?", (tid,))
        return _row(await cur.fetchone())


async def list_tickets(user_id: int, limit: int, offset: int) -> List[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute("SELECT * FROM wa_tickets WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                              (user_id, limit, offset))
        return [dict(r) for r in await cur.fetchall()]


async def get_ticket(ticket_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    q, args = "SELECT * FROM wa_tickets WHERE id=?", [ticket_id]
    if user_id is not None:
        q += " AND user_id=?"
        args.append(user_id)
    async with conn() as c:
        cur = await c.execute(q, args)
        t = _row(await cur.fetchone())
        if not t:
            return None
        cur = await c.execute("SELECT sender, body, created_at FROM wa_ticket_messages WHERE ticket_id=? ORDER BY id",
                              (ticket_id,))
        t["messages"] = [dict(r) for r in await cur.fetchall()]
        return t


async def add_ticket_message(ticket_id: int, sender: str, body: str) -> None:
    t = now()
    async with conn() as c:
        await c.execute("INSERT INTO wa_ticket_messages(ticket_id,sender,body,created_at) VALUES(?,?,?,?)",
                        (ticket_id, sender, body, t))
        await c.execute("UPDATE wa_tickets SET status=?, updated_at=? WHERE id=?",
                        ("answered" if sender == "admin" else "open", t, ticket_id))


async def close_ticket(ticket_id: int, user_id: Optional[int] = None) -> bool:
    q, args = "UPDATE wa_tickets SET status='closed', updated_at=? WHERE id=?", [now(), ticket_id]
    if user_id is not None:
        q += " AND user_id=?"
        args.append(user_id)
    async with conn() as c:
        cur = await c.execute(q, args)
        return cur.rowcount == 1


async def count_open_tickets(user_id: int) -> int:
    async with conn() as c:
        cur = await c.execute("SELECT COUNT(*) FROM wa_tickets WHERE user_id=? AND status!='closed'", (user_id,))
        return (await cur.fetchone())[0]


async def unsubmit_receipt(order_id: int) -> None:
    """اگر ارسال رسید به هیچ ادمینی نرسید، سفارش به حالت قبل برمی‌گردد تا کاربر بتواند دوباره تلاش کند."""
    async with conn() as c:
        await c.execute("UPDATE wa_orders SET payment_status='unpaid', updated_at=? "
                        "WHERE id=? AND status='pending_payment' AND payment_status='awaiting_review'",
                        (now(), order_id))


async def drop_usage_cache(panel_username: str) -> None:
    async with conn() as c:
        await c.execute("DELETE FROM wa_usage_cache WHERE panel_username=?", (panel_username,))


async def get_user_row(user_id: int) -> Optional[Dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute("SELECT user_id, username, full_name, joined_at FROM users WHERE user_id=?", (user_id,))
        return _row(await cur.fetchone())
