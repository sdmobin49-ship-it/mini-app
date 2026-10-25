import asyncio
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from urllib.parse import urlencode

from tests import stubs
stubs.install()

import config  # noqa: E402
import database as db  # noqa: E402
from webapp import auth, catalog, panel, service, settings, store, server  # noqa: E402
from webapp.service import ApiError  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
U1, U2 = 111111, 222222


def make_init_data(uid, auth_date=None, token=None, tamper=False):
    token = token or config.BOT_TOKEN
    d = {"auth_date": str(int(auth_date if auth_date is not None else time.time())), "query_id": "AAH",
         "user": json.dumps({"id": uid, "first_name": "T"}, separators=(",", ":"))}
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    h = hmac.new(hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest(), s.encode(), hashlib.sha256).hexdigest()
    if tamper:
        d["user"] = json.dumps({"id": uid + 1})
    return urlencode({**d, "hash": h})


class FakePanel:
    def __init__(self):
        self.users, self.down = {}, False
        self.lose_create_response = False
        self.fail_set_limits = 0
        self.calls = {"create": 0, "reset": 0, "set": 0, "fetch": 0}

    async def fetch_user(self, st, u):
        self.calls["fetch"] += 1
        if self.down:
            raise ConnectionError("panel down")
        return self.users.get(u)

    async def create_user(self, st, u, plan):
        if self.down:
            raise ConnectionError("panel down")
        self.calls["create"] += 1
        self.users[u] = {"username": u, "status": "active", "used_traffic": 0,
                         "data_limit": (plan.get("data_limit_gb") or 0) * 1024 ** 3,
                         "expire": int(time.time()) + plan["duration_days"] * 86400,
                         "subscription_url": f"https://sub.example/{u}", "proxies": {"vless": {}}}
        if self.lose_create_response:
            self.lose_create_response = False
            raise TimeoutError("response lost")
        return self.users[u]

    async def reset_traffic(self, st, u):
        self.calls["reset"] += 1
        self.users[u]["used_traffic"] = 0
        return True

    async def set_limits(self, st, u, exp, gb):
        if self.fail_set_limits > 0:
            self.fail_set_limits -= 1
            raise ConnectionError("boom")
        self.calls["set"] += 1
        self.users[u].update(expire=exp, status="active")
        if gb is not None:
            self.users[u]["data_limit"] = gb * 1024 ** 3
        return self.users[u]


class FakeNotifier:
    def __init__(self):
        self.user_msgs, self.alerts, self.receipts, self.tickets = [], [], [], []
        self.receipt_ok = True

    async def user(self, uid, text): self.user_msgs.append((uid, text))
    async def admins_alert(self, text, order_id=None): self.alerts.append((text, order_id))
    async def admins_receipt(self, order, image, caption):
        self.receipts.append(order["id"])
        return "fileid" if self.receipt_ok else None
    async def admins_ticket(self, t, body): self.tickets.append(t["id"])


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "t.db")
        shutil.copy(os.path.join(ROOT, "vpn_bot.db"), self.path)     # اسکیمای واقعی ربات
        db.DB_PATH = self.path
        await store.migrate()
        con = sqlite3.connect(self.path)
        con.execute("DELETE FROM balance WHERE user_id IN (?,?)", (U1, U2))
        con.execute("DELETE FROM services WHERE user_id IN (?,?)", (U1, U2))
        for u in (U1, U2):
            con.execute("INSERT OR REPLACE INTO users(user_id,username,full_name) VALUES(?,?,?)", (u, f"u{u}", f"User {u}"))
        con.commit(); con.close()
        self.p, self.n = FakePanel(), FakeNotifier()
        self._orig = {k: getattr(panel, k) for k in ("fetch_user", "create_user", "reset_traffic", "set_limits")}
        panel.fetch_user, panel.create_user = self.p.fetch_user, self.p.create_user
        panel.reset_traffic, panel.set_limits = self.p.reset_traffic, self.p.set_limits
        service.notifier = self.n
        service._usage_mem.clear()
        self._plans = {k: dict(v) for k, v in config.PLANS.items()}

    async def asyncTearDown(self):
        for k, v in self._orig.items():
            setattr(panel, k, v)
        config.PLANS.clear(); config.PLANS.update(self._plans)
        service.notifier = service._NoopNotifier()
        await asyncio.sleep(0.05)
        shutil.rmtree(self.dir, ignore_errors=True)

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path); r = con.execute(q, a).fetchall(); con.commit(); con.close(); return r

    async def fund(self, uid, amount):
        await db.add_balance(uid, amount)

    async def order(self, uid=U1, body=None, key=None):
        body = body or {"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1"}
        return await service.create_order(uid, body, key or ("k" + os.urandom(8).hex()))

    async def buy(self, uid=U1, body=None):
        await self.fund(uid, 10_000_000)
        o = await self.order(uid, body)
        return await service.pay_order(uid, o["id"], "balance")

    def service_id(self, uid=U1):
        return self.sql("SELECT id FROM services WHERE user_id=? ORDER BY id DESC", (uid,))[0][0]

    def due(self, oid):   # شبیه‌سازی گذشتن زمان backoff
        self.sql("UPDATE wa_orders SET next_retry_at=1 WHERE id=?", (oid,))


# ═════════════════ احراز هویت ═════════════════
class TestAuth(Base):
    def test_valid(self):
        self.assertEqual(auth.validate_init_data(make_init_data(U1), config.BOT_TOKEN, 3600)["id"], U1)

    def test_invalid_cases(self):
        for init, code in [(make_init_data(U1, tamper=True), "invalid_signature"),
                           (make_init_data(U1, token="1:wrong"), "invalid_signature"),
                           (make_init_data(U1, auth_date=time.time() - 7200), "init_data_expired"),
                           (make_init_data(U1, auth_date=time.time() + 3600), "invalid_init_data"),
                           ("", "invalid_init_data"), ("user=%7B%7D", "invalid_init_data")]:
            with self.assertRaises(auth.AuthError) as c:
                auth.validate_init_data(init, config.BOT_TOKEN, 3600)
            self.assertEqual(c.exception.code, code)

    def test_tokens(self):
        t = auth.issue_token(U1)
        self.assertEqual(auth.verify_token(t)["uid"], U1)
        with self.assertRaises(auth.AuthError):
            auth.verify_token(t[:-2] + "xx")
        with self.assertRaises(auth.AuthError) as c:
            auth.verify_token(auth.issue_token(U1, now=1000, ttl=10))
        self.assertEqual(c.exception.code, "session_expired")
        with self.assertRaises(auth.AuthError):
            auth.verify_token(t, secret="other")


# ═════════════════ HTTP (middleware و کنترل دسترسی) ═════════════════
class TestHttp(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        server.LIMITER._hits.clear()
        self.app = server.build_app(bot=None)

    async def call(self, m, p, uid=U1, **kw):
        h = {"Authorization": "Bearer " + auth.issue_token(uid)} if uid else {}
        h.update(kw.pop("headers", {}))
        return await stubs.http_call(self.app, m, p, headers=h, **kw)

    async def test_login_flow_and_unauthorized(self):
        s, j = await stubs.http_call(self.app, "POST", "/api/v1/auth/telegram", json_body={"init_data": make_init_data(U1)})
        self.assertEqual(s, 200); self.assertTrue(j["data"]["token"])
        s, j = await stubs.http_call(self.app, "POST", "/api/v1/auth/telegram", json_body={"init_data": make_init_data(U1, tamper=True)})
        self.assertEqual((s, j["error"]["code"]), (401, "invalid_signature"))
        s, j = await stubs.http_call(self.app, "POST", "/api/v1/auth/telegram", json_body={"init_data": make_init_data(999999999)})
        self.assertEqual((s, j["error"]["code"]), (403, "not_registered"))
        for path in ("/api/v1/me", "/api/v1/services", "/api/v1/orders"):
            s, j = await self.call("GET", path, uid=None)
            self.assertEqual((s, j["error"]["code"]), (401, "unauthorized"))
        s, _ = await stubs.http_call(self.app, "GET", "/api/v1/me", headers={"Authorization": "Bearer garbage"})
        self.assertEqual(s, 401)

    async def test_logout_revokes_old_tokens(self):
        old = auth.issue_token(U1, now=int(time.time()) - 5)
        s, _ = await stubs.http_call(self.app, "GET", "/api/v1/me", headers={"Authorization": "Bearer " + old})
        self.assertEqual(s, 200)
        await store.revoke_sessions(U1)
        s, j = await stubs.http_call(self.app, "GET", "/api/v1/me", headers={"Authorization": "Bearer " + old})
        self.assertEqual((s, j["error"]["code"]), (401, "session_revoked"))
        s, _ = await self.call("GET", "/api/v1/me", headers={"Authorization": "Bearer " + auth.issue_token(U1, now=int(time.time()) + 5)})
        self.assertEqual(s, 200)

    async def test_idor(self):
        await self.buy(U1)
        sid = self.service_id(U1)
        s, _ = await self.call("GET", f"/api/v1/services/{sid}", uid=U1); self.assertEqual(s, 200)
        for m, p in [("GET", f"/api/v1/services/{sid}"), ("GET", f"/api/v1/services/{sid}/usage"),
                     ("POST", f"/api/v1/services/{sid}/config"), ("GET", f"/api/v1/services/{sid}/renew-plans")]:
            s, j = await self.call(m, p, uid=U2); self.assertEqual((s, j["error"]["code"]), (404, "not_found"), p)
        s, j = await self.call("POST", f"/api/v1/services/{sid}/renew", uid=U2, json_body={"plan_id": "unlimited_1m_1u"},
                               headers={"Idempotency-Key": "abcdefgh1234"})
        self.assertEqual(s, 404)
        oid = self.sql("SELECT public_id FROM wa_orders WHERE user_id=?", (U1,))[0][0]
        s, _ = await self.call("GET", f"/api/v1/orders/{oid}", uid=U2); self.assertEqual(s, 404)
        s, _ = await self.call("POST", f"/api/v1/orders/{oid}/payment", uid=U2, json_body={"method": "balance"}); self.assertEqual(s, 404)
        t = await service.create_ticket(U1, "other", "subject", "hello there")
        s, _ = await self.call("GET", f"/api/v1/support/tickets/{t['id']}", uid=U2); self.assertEqual(s, 404)
        s, _ = await self.call("POST", f"/api/v1/support/tickets/{t['id']}/close", uid=U2); self.assertEqual(s, 404)

    async def test_rate_limit_and_no_stack_trace_and_no_secrets(self):
        await self.fund(U1, 10_000_000)
        codes = []
        for _ in range(32):
            s, _ = await self.call("POST", "/api/v1/quote", json_body={"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1"})
            codes.append(s)
        self.assertEqual(codes[:1], [200]); self.assertIn(429, codes)
        orig = service.dashboard
        async def boom(uid): raise RuntimeError("secret internal detail /home/x.py")
        service.dashboard = boom
        try:
            s, j = await self.call("GET", "/api/v1/dashboard")
        finally:
            service.dashboard = orig
        self.assertEqual((s, j["error"]["code"]), (500, "internal_error"))
        self.assertNotIn("secret internal", json.dumps(j))
        await self.buy(U1)
        blob = ""
        for p in ("/api/v1/me", "/api/v1/dashboard", "/api/v1/services?usage=1", "/api/v1/plans", "/api/v1/orders"):
            _, j = await self.call("GET", p); blob += json.dumps(j)
        for secret in (config.BOT_TOKEN, config.PANEL_PASSWORD, config.PANEL_URL):
            self.assertNotIn(secret, blob)

    async def test_payment_multipart_card(self):
        class F:  # شبیه فایل آپلودی aiohttp
            def __init__(s, b): s.file = type("X", (), {"read": lambda self, n=-1: b[:n] if n > 0 else b})()
        o = await self.order()
        s, j = await self.call("POST", f"/api/v1/orders/{o['id']}/payment", form={"method": "card", "receipt": F(PNG)})
        self.assertEqual(s, 200); self.assertEqual(j["data"]["payment_status"], "awaiting_review")
        s, j = await self.call("POST", f"/api/v1/orders/{o['id']}/payment", form={"method": "card", "receipt": F(PNG)})
        self.assertEqual((s, j["error"]["code"]), (409, "already_submitted"))


# ═════════════════ خرید و پرداخت ═════════════════
class TestPurchase(Base):
    async def test_volume_and_unlimited(self):
        o = await self.buy()
        self.assertEqual(o["status"], "completed")
        self.assertEqual(await db.get_balance(U1), 10_000_000 - config.PLANS["plan_1"]["price"])
        o2 = await self.buy(body={"kind": "purchase", "service_type": "unlimited", "plan_id": "unlimited_1m_1u"})
        self.assertEqual(o2["status"], "completed")
        rows = self.sql("SELECT service_type, subscription_url FROM services WHERE user_id=? ORDER BY id", (U1,))
        self.assertEqual([r[0] for r in rows], ["cdn", "unlimited"]); self.assertTrue(all(r[1] for r in rows))
        u = (await service.get_service(U1, self.service_id()))["usage"]
        self.assertIsNone(u["limit_bytes"])      # نامحدود
        self.assertEqual(u["status"], "active")

    async def test_plan_validation_and_client_price_ignored(self):
        with self.assertRaises(ApiError) as c:
            await self.order(body={"kind": "purchase", "service_type": "cdn", "plan_id": "nope"})
        self.assertEqual(c.exception.code, "plan_not_found")
        with self.assertRaises(ApiError):
            await self.order(body={"kind": "purchase", "service_type": "x", "plan_id": "plan_1"})
        o = await self.order(body={"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1", "amount": 1, "price": 1})
        self.assertEqual(o["amount"], config.PLANS["plan_1"]["price"])

    async def test_inactive_plan_and_price_change_after_order(self):
        await self.fund(U1, 10_000_000)
        o = await self.order()
        orig = o["amount"]
        config.PLANS["plan_1"]["price"] = orig * 3          # تغییر قیمت بعد از ساخت سفارش
        done = await service.pay_order(U1, o["id"], "balance")
        self.assertEqual(await db.get_balance(U1), 10_000_000 - orig)   # همان قیمت فریزشده
        self.assertEqual(done["status"], "completed")
        del config.PLANS["plan_1"]                           # پلن غیرفعال/حذف‌شده
        self.assertNotIn("plan_1", [p["id"] for p in catalog.list_plans("cdn")])
        with self.assertRaises(ApiError) as c:
            await self.order()
        self.assertEqual(c.exception.status, 404)

    async def test_double_click_and_idempotency(self):
        await self.fund(U1, 10_000_000)
        o = await service.create_order(U1, {"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1"}, "same-key-123")
        o_again = await service.create_order(U1, {"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1"}, "same-key-123")
        self.assertEqual(o["id"], o_again["id"])
        with self.assertRaises(ApiError):
            await service.create_order(U1, {"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1"}, None)
        res = await asyncio.gather(*[service.pay_order(U1, o["id"], "balance") for _ in range(5)], return_exceptions=True)
        self.assertEqual(await db.get_balance(U1), 10_000_000 - o["amount"])      # فقط یک‌بار کسر
        self.assertEqual(len(self.sql("SELECT 1 FROM services WHERE user_id=?", (U1,))), 1)
        self.assertEqual(self.p.calls["create"], 1)
        self.assertFalse([r for r in res if isinstance(r, Exception)])

    async def test_insufficient_balance(self):
        await self.fund(U1, 1000)
        o = await self.order()
        with self.assertRaises(ApiError) as c:
            await service.pay_order(U1, o["id"], "balance")
        self.assertEqual(c.exception.code, "insufficient_balance")
        self.assertEqual(await db.get_balance(U1), 1000)
        self.assertEqual((await service.get_order(U1, o["id"]))["status"], "pending_payment")

    async def test_concurrent_balance_race_spend_balance(self):
        await self.fund(U1, 100)
        r = await asyncio.gather(*[db.spend_balance(U1, 100) for _ in range(6)])
        self.assertEqual(sum(r), 1); self.assertEqual(await db.get_balance(U1), 0)

    async def test_card_flow_pending_approve_reject(self):
        o = await self.order()
        with self.assertRaises(ApiError) as c:
            await service.pay_order(U1, o["id"], "card", b"not an image")
        self.assertEqual(c.exception.code, "invalid_receipt")
        self.n.receipt_ok = False
        with self.assertRaises(ApiError) as c:
            await service.pay_order(U1, o["id"], "card", PNG)
        self.assertEqual(c.exception.code, "admin_unreachable")
        self.assertEqual((await service.get_order(U1, o["id"]))["payment_status"], "unpaid")   # برگشت وضعیت
        self.n.receipt_ok = True
        r = await service.pay_order(U1, o["id"], "card", PNG)
        self.assertEqual((r["status"], r["payment_status"]), ("pending_payment", "awaiting_review"))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM services WHERE user_id=?", (U1,))[0][0], 0)   # هنوز فعال نشده
        oid = self.sql("SELECT id FROM wa_orders WHERE public_id=?", (o["id"],))[0][0]
        self.assertEqual(await service.approve_order(oid, 1), "approved")
        self.assertEqual(await service.approve_order(oid, 1), "already_processed")
        await asyncio.sleep(0.2)
        self.assertEqual((await service.get_order(U1, o["id"]))["status"], "completed")
        self.assertEqual(self.p.calls["create"], 1)
        o2 = await self.order(); await service.pay_order(U1, o2["id"], "card", PNG)
        oid2 = self.sql("SELECT id FROM wa_orders WHERE public_id=?", (o2["id"],))[0][0]
        self.assertEqual(await service.reject_order(oid2, 1), "rejected")
        self.assertEqual(await service.approve_order(oid2, 1), "already_processed")

    async def test_discount(self):
        await db.create_discount_code("OFF50", 50, 1, None)
        await self.fund(U1, 10_000_000)
        base = config.PLANS["plan_1"]["price"]
        o = await self.order(body={"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1", "discount_code": "off50"})
        self.assertEqual(o["amount"], base // 2)
        await service.pay_order(U1, o["id"], "balance")
        with self.assertRaises(ApiError) as c:     # سقف استفاده‌ی هر کاربر
            await self.order(body={"kind": "purchase", "service_type": "cdn", "plan_id": "plan_1", "discount_code": "OFF50"})
        self.assertEqual(c.exception.code, "discount_invalid")
        with self.assertRaises(ApiError):
            await service.quote(U1, {"kind": "topup", "amount": 20000, "discount_code": "OFF50"})


# ═════════════════ فعال‌سازی و بازیابی ═════════════════
class TestProvisioning(Base):
    async def test_panel_down_then_recover(self):
        await self.fund(U1, 10_000_000)
        o = await self.order()
        self.p.down = True
        r = await service.pay_order(U1, o["id"], "balance")
        self.assertEqual(r["status"], "failed"); self.assertEqual(r["payment_status"], "paid")   # پرداخت ثبت شد
        self.assertEqual(await db.get_balance(U1), 10_000_000 - o["amount"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM services WHERE user_id=?", (U1,))[0][0], 0)
        self.assertNotIn("panel down", json.dumps(r))        # خطای خام به کاربر نمی‌رسد
        oid = self.sql("SELECT id FROM wa_orders")[0][0]
        self.assertIsNone(await service.provision(oid))      # هنوز زمان تلاش مجدد نرسیده
        self.p.down = False; self.due(oid)
        self.assertEqual(await service.provision(oid), "completed")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM services WHERE user_id=?", (U1,))[0][0], 1)
        self.assertEqual(self.p.calls["create"], 1)

    async def test_lost_create_response_no_duplicate(self):
        await self.fund(U1, 10_000_000)
        o = await self.order()
        self.p.lose_create_response = True
        r = await service.pay_order(U1, o["id"], "balance")
        self.assertEqual(r["status"], "failed")
        oid = self.sql("SELECT id FROM wa_orders")[0][0]; self.due(oid)
        await service.provision(oid)
        self.assertEqual(self.p.calls["create"], 1)          # کاربر ساخته‌شده‌ی قبلی adopt شد
        self.assertEqual(len(self.p.users), 1)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM services WHERE user_id=?", (U1,))[0][0], 1)

    async def test_invalid_panel_response_retries(self):
        await self.fund(U1, 10_000_000)
        async def bad(*a): return None                        # پاسخ نامعتبر/ناموفق
        panel.create_user = bad
        o = await self.order(); r = await service.pay_order(U1, o["id"], "balance")
        self.assertEqual(r["status"], "failed")

    async def test_concurrent_provision_single_create(self):
        await self.fund(U1, 10_000_000)
        o = await self.order()
        await store.pay_with_balance(self.sql("SELECT id FROM wa_orders")[0][0], U1)
        oid = self.sql("SELECT id FROM wa_orders")[0][0]
        await asyncio.gather(*[service.provision(oid) for _ in range(4)])
        self.assertEqual(self.p.calls["create"], 1)

    async def test_crash_mid_provisioning_is_reclaimed(self):
        await self.fund(U1, 10_000_000)
        o = await self.order()
        oid = self.sql("SELECT id FROM wa_orders")[0][0]
        await store.pay_with_balance(oid, U1)
        self.assertIsNotNone(await store.claim_provisioning(oid, 180))     # پروسه می‌میرد قبل از پایان
        self.assertIsNone(await store.claim_provisioning(oid, 180))
        self.sql("UPDATE wa_orders SET updated_at=updated_at-1000 WHERE id=?", (oid,))
        self.assertIn(oid, await store.due_order_ids(180))
        self.assertEqual(await service.provision(oid), "completed")

    async def test_permanent_failure_refund_balance_and_card_alert(self):
        await self.fund(U1, 10_000_000)
        self.p.down = True
        o = await self.order(); await service.pay_order(U1, o["id"], "balance")
        oid = self.sql("SELECT id FROM wa_orders")[0][0]
        for _ in range(settings.MAX_PROVISION_ATTEMPTS):
            self.due(oid); await service.provision(oid)
        row = self.sql("SELECT status FROM wa_orders WHERE id=?", (oid,))[0][0]
        self.assertEqual(row, "refunded"); self.assertEqual(await db.get_balance(U1), 10_000_000)
        self.assertFalse(await store.refund_to_balance(oid))               # بازگشت وجه دوباره ممکن نیست
        # کارت: refund خودکار نمی‌شود، ادمین هشدار می‌گیرد و می‌تواند retry کند
        o2 = await self.order(); await service.pay_order(U1, o2["id"], "card", PNG)
        oid2 = self.sql("SELECT id FROM wa_orders WHERE public_id=?", (o2["id"],))[0][0]
        await service.approve_order(oid2, 1); await asyncio.sleep(0.2)
        for _ in range(settings.MAX_PROVISION_ATTEMPTS):
            self.due(oid2); await service.provision(oid2)
        self.assertEqual(self.sql("SELECT status FROM wa_orders WHERE id=?", (oid2,))[0][0], "failed")
        self.assertTrue(self.n.alerts)
        self.p.down = False
        self.assertTrue(await store.reset_for_retry(oid2))
        self.assertEqual(await service.provision(oid2), "completed")

    async def test_topup_credits_once(self):
        o = await service.create_order(U1, {"kind": "topup", "amount": 50000}, "topup-key-1")
        with self.assertRaises(ApiError):
            await service.pay_order(U1, o["id"], "balance")
        with self.assertRaises(ApiError):
            await service.create_order(U1, {"kind": "topup", "amount": 5}, "topup-key-2")
        await service.pay_order(U1, o["id"], "card", PNG)
        oid = self.sql("SELECT id FROM wa_orders")[0][0]
        await service.approve_order(oid, 1); await service.approve_order(oid, 1)
        await asyncio.gather(service.provision(oid), service.provision(oid)); await asyncio.sleep(0.2)
        self.assertEqual(await db.get_balance(U1), 50000)

    async def test_renew_unlimited_and_volume_idempotent(self):
        await self.buy(body={"kind": "purchase", "service_type": "unlimited", "plan_id": "unlimited_1m_1u"})
        sid = self.service_id(); uname = self.sql("SELECT panel_username FROM services WHERE id=?", (sid,))[0][0]
        before = self.p.users[uname]["expire"]
        self.p.fail_set_limits = 1                                   # اولین تلاش وسط تمدید خراب می‌شود
        o = await service.create_order(U1, {"kind": "renew", "service_id": sid, "plan_id": "unlimited_1m_1u"}, "renew-key-1")
        r = await service.pay_order(U1, o["id"], "balance")
        self.assertEqual(r["status"], "failed")
        oid = self.sql("SELECT id FROM wa_orders WHERE public_id=?", (o["id"],))[0][0]
        self.due(oid); await service.provision(oid)
        self.assertEqual(self.p.users[uname]["expire"], before + 30 * 86400)     # فقط یک‌بار تمدید
        # حجمی: reset فقط یک‌بار حتی با retry
        await self.buy()
        vsid = self.service_id(); vu = self.sql("SELECT panel_username FROM services WHERE id=?", (vsid,))[0][0]
        self.p.users[vu]["used_traffic"] = 5 * 1024 ** 3
        self.p.fail_set_limits = 1; resets = self.p.calls["reset"]
        o = await service.create_order(U1, {"kind": "renew", "service_id": vsid, "plan_id": "plan_2"}, "renew-key-2")
        await service.pay_order(U1, o["id"], "balance")
        oid = self.sql("SELECT id FROM wa_orders WHERE public_id=?", (o["id"],))[0][0]
        self.due(oid); await service.provision(oid)
        self.assertEqual(self.p.calls["reset"], resets + 1)
        self.assertEqual(self.p.users[vu]["used_traffic"], 0)
        self.assertEqual(self.p.users[vu]["data_limit"], config.PLANS["plan_2"]["data_limit_gb"] * 1024 ** 3)
        with self.assertRaises(ApiError):     # پلن نامعتبر
            await service.create_order(U1, {"kind": "renew", "service_id": vsid, "plan_id": "zzz"}, "renew-key-3")


# ═════════════════ مصرف ═════════════════
class TestUsage(Base):
    async def test_volume_unlimited_cache_stale_unavailable(self):
        await self.buy(); sid = self.service_id()
        u = await service.get_usage(U1, sid)
        self.assertEqual(u["limit_bytes"], config.PLANS["plan_1"]["data_limit_gb"] * 1024 ** 3)
        self.assertEqual(u["remaining_bytes"], u["limit_bytes"]); self.assertFalse(u["stale"])
        n = self.p.calls["fetch"]
        await service.get_usage(U1, sid); self.assertEqual(self.p.calls["fetch"], n)       # کش کوتاه‌عمر
        await service.get_usage(U1, sid, force=True); self.assertEqual(self.p.calls["fetch"], n + 1)
        self.p.down = True
        u = await service.get_usage(U1, sid, force=True)
        self.assertTrue(u["available"] and u["stale"]); self.assertTrue(u["fetched_at"])    # آخرین داده ذخیره‌شده
        self.sql("DELETE FROM wa_usage_cache"); service._usage_mem.clear()
        u = await service.get_usage(U1, sid, force=True)
        self.assertFalse(u["available"]); self.assertIsNone(u["used_bytes"])               # نه صفر گمراه‌کننده
        d = await service.dashboard(U1)                                                     # داشبورد با پنل خراب نمی‌افتد
        self.assertEqual(d["services_total"], 1)

    def test_legacy_type_resolution(self):
        self.assertEqual(panel.resolve_type("SPIDERabc", "paid"), "cdn")
        self.assertEqual(panel.resolve_type("SPIDERabc", "unlimited"), "unlimited")
        self.assertEqual(panel.resolve_type("S_TUNNEL_x", "free"), "tunnel")
        self.assertEqual(panel.normalize({"status": "active", "expire": 5, "data_limit": 0}, now=10)["status"], "expired")


# ═════════════════ پشتیبانی ═════════════════
class TestSupport(Base):
    async def test_tickets(self):
        with self.assertRaises(ApiError):
            await service.create_ticket(U1, "bad", "subject", "body text")
        with self.assertRaises(ApiError):
            await service.create_ticket(U1, "other", "x", "body text")
        for i in range(5):
            await service.create_ticket(U1, "other", f"subject {i}", "hello there")
        with self.assertRaises(ApiError) as c:
            await service.create_ticket(U1, "other", "subject 6", "hello there")
        self.assertEqual(c.exception.status, 429)
        tid = (await service.list_tickets(U1, 10, 0))[0]["id"]
        self.assertEqual(await service.admin_reply_ticket(tid, "answer"), U1)
        t = await service.get_ticket(U1, tid)
        self.assertEqual((t["status"], t["messages"][-1]["sender"]), ("answered", "admin"))
        await service.reply_ticket(U1, tid, "thanks")
        with self.assertRaises(ApiError):
            await service.get_ticket(U2, tid)
        self.assertEqual(len(self.n.tickets), 6)


# ═════════════════ سازگاری با دیتابیس واقعی ═════════════════
class TestCompat(Base):
    async def test_migration_preserves_data_and_is_idempotent(self):
        fresh = os.path.join(self.dir, "orig.db"); shutil.copy(os.path.join(ROOT, "vpn_bot.db"), fresh)
        con = sqlite3.connect(fresh)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'wa_%'")]
        snap = {t: con.execute(f"SELECT * FROM {t} ORDER BY 1,2").fetchall() for t in tables}; con.close()
        db.DB_PATH = fresh
        await store.migrate(); await store.migrate()
        con = sqlite3.connect(fresh)
        for t in tables:
            self.assertEqual(con.execute(f"SELECT * FROM {t} ORDER BY 1,2").fetchall(), snap[t], t)
        self.assertEqual(con.execute("SELECT value FROM wa_meta WHERE key='schema_version'").fetchone()[0], "1")
        self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok"); con.close()

    async def test_real_user_dashboard_and_services(self):
        con = sqlite3.connect(self.path)
        uid = con.execute("SELECT user_id FROM services GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
        real = con.execute("SELECT panel_username, service_type FROM services WHERE user_id=?", (uid,)).fetchall(); con.close()
        for uname, st in real:
            self.p.users[uname] = {"status": "active", "used_traffic": 1, "data_limit": 0, "expire": int(time.time()) + 86400 * 9,
                                   "proxies": {"vless": {}}}
        d = await service.dashboard(uid)
        self.assertEqual(d["services_total"], len(real)); self.assertGreaterEqual(d["services_active"], 1)
        acc = await service.account(uid, "bot"); self.assertIn("referral", acc)
        page = await service.list_services(uid, True, 50, 0)
        self.assertTrue(all(i["plan_name"] for i in page["items"]))      # پلن‌های قدیمی هم برچسب دارند


if __name__ == "__main__":
    unittest.main(verbosity=2)
