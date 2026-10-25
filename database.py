import aiosqlite
import logging
from typing import Optional, Dict, Any, List

import os
DB_PATH = os.getenv("DB_PATH", "vpn_bot.db")  # روی Railway به مسیر Volume اشاره بده (مثلاً /data/vpn_bot.db)
logger = logging.getLogger(__name__)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id      INTEGER PRIMARY KEY,
                username     TEXT,
                full_name    TEXT,
                referred_by  INTEGER DEFAULT NULL,
                joined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER,
                panel_username   TEXT UNIQUE,
                plan_id          TEXT,
                subscription_url TEXT,
                service_type     TEXT DEFAULT 'paid',
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                plan_id     TEXT,
                service_type TEXT DEFAULT 'cdn',
                status       TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id  INTEGER,
                referred_id  INTEGER UNIQUE,
                rewarded     INTEGER DEFAULT 0,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referral_points (
                user_id  INTEGER PRIMARY KEY,
                points   INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0
            )
        """)
        # جدول تنظیمات متن‌ها برای ویرایش از پنل ادمین
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_texts (
                key    TEXT PRIMARY KEY,
                value  TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balance (
                user_id  INTEGER PRIMARY KEY,
                amount   INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                panel_username TEXT,
                warn_type   TEXT,
                sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(panel_username, warn_type)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS discount_codes (
                code           TEXT PRIMARY KEY,
                percent        INTEGER NOT NULL,
                max_per_user   INTEGER NOT NULL DEFAULT 1,
                expires_at     TIMESTAMP,
                is_active      INTEGER DEFAULT 1,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # استفاده‌های ثبت‌شده از کد تخفیف (هر ردیف = یک استفاده تأییدشده)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS discount_usages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT,
                user_id     INTEGER,
                used_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # ایموجی پرمیوم اختصاص‌یافته به هر دکمه (کلید = شناسه دکمه)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS button_emojis (
                button_key  TEXT PRIMARY KEY,
                emoji_id    TEXT NOT NULL,
                fallback    TEXT DEFAULT '😀'
            )
        """)
        # migration حداقلی برای دیتابیس‌های قدیمی
        async with db.execute("PRAGMA table_info(orders)") as cur:
            order_columns = {row[1] for row in await cur.fetchall()}
        if "service_type" not in order_columns:
            await db.execute("ALTER TABLE orders ADD COLUMN service_type TEXT DEFAULT 'cdn'")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_purchases (
                purchase_id    TEXT PRIMARY KEY,
                user_id        INTEGER,
                plan_id        TEXT,
                panel_username TEXT,
                price          INTEGER,
                code           TEXT,
                is_unlimited   INTEGER,
                service_type   TEXT DEFAULT 'cdn',
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        async with db.execute("PRAGMA table_info(pending_purchases)") as cur:
            pending_columns = {row[1] for row in await cur.fetchall()}
        if "service_type" not in pending_columns:
            await db.execute("ALTER TABLE pending_purchases ADD COLUMN service_type TEXT DEFAULT 'cdn'")

        # مقادیر پیش‌فرض متن‌ها
        default_texts = [
            ("welcome_msg",
             "👋 سلام {name} عزیز!\n\n🌐 به ربات فروش VPN خوش اومدی\n\n"
             "✨ <b>ویژگی‌های ما:</b>\n"
             "  ├ 🚀 سرعت بالا و پایداری عالی\n"
             "  ├ 🔒 امنیت کامل با پروتکل‌های جدید\n"
             "  ├ 🌍 سرور اختصاصی با IP تمیز\n"
             "  └ 🛟 پشتیبانی ۲۴ ساعته\n\n"
             "از منوی زیر گزینه مورد نظرت رو انتخاب کن 👇"),
            ("buy_msg",
             "🛒 <b>انتخاب پلن</b>\n\n"
             "یکی از پلن‌های زیر رو انتخاب کن:\n\n"
             "💡 همه پلن‌ها شامل:\n"
             "  ✅ سرعت نامحدود\n"
             "  ✅ بدون محدودیت پلتفرم\n"
             "  ✅ پشتیبانی از همه دستگاه‌ها"),
            ("payment_msg",
             "💳 <b>اطلاعات پرداخت</b>\n\n"
             "مبلغ: <b>{price} تومان</b>\n\n"
             "شماره کارت:\n<code>{card}</code>\n\n"
             "به نام: <b>{owner}</b>\n\n"
             "━━━━━━━━━━━━━━━\n"
             "⚠️ بعد از واریز روی «پرداخت کردم» بزن و <b>تصویر رسید</b> ارسال کن."),
            ("service_activated_msg",
             "🎉 <b>سرویس شما فعال شد!</b>\n\n"
             "📦 پلن: {plan_name}\n"
             "💾 حجم: {data_gb} گیگابایت\n"
             "📅 مدت: {days} روز\n\n"
             "🔗 <b>لینک اشتراک:</b>\n<code>{sub_url}</code>\n\n"
             "👆 این لینک رو در اپ VPN وارد کن.\n"
             "برای راهنمای نصب روی «راهنما» بزن 👇"),
            ("support_msg",
             "📞 <b>پشتیبانی</b>\n\n"
             "برای ارتباط با پشتیبانی از دکمه زیر استفاده کن:\n\n"
             "⏰ ساعات پاسخگویی: همه روزه ۹ صبح تا ۱۲ شب"),
            ("referral_msg",
             "🎁 <b>سیستم رفرال</b>\n\n"
             "با دعوت دوستانت سرویس رایگان بگیر!\n\n"
             "🔗 لینک دعوت تو:\n<code>{ref_link}</code>\n\n"
             "📊 امتیاز فعلی: <b>{points}</b> امتیاز\n"
             "👥 تعداد دعوت‌شدگان: <b>{total_refs}</b> نفر\n\n"
             "━━━━━━━━━━━━━━━\n"
             "🏆 هر دعوت موفق = ۱ امتیاز\n"
             "🎁 هر ۵ امتیاز = ۱ گیگ سرویس رایگان ۳۰ روزه"),
        ]
        for key, val in default_texts:
            await db.execute(
                "INSERT OR IGNORE INTO bot_texts (key, value) VALUES (?, ?)",
                (key, val)
            )
        await db.commit()


# ─── Users ────────────────────────────────────────────────────────
async def save_user(user_id: int, username: str, full_name: str, referred_by: Optional[int] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name, referred_by)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, full_name, referred_by))
        await db.commit()


async def user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone() is not None


async def get_user_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]


# ─── Services ────────────────────────────────────────────────────
async def save_service(user_id: int, panel_username: str, plan_id: str,
                       subscription_url: str, service_type: str = "paid"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO services
                (user_id, panel_username, plan_id, subscription_url, service_type)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, panel_username, plan_id, subscription_url, service_type))
        await db.commit()


async def get_user_service(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT panel_username, plan_id, subscription_url, created_at, service_type
            FROM services WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "panel_username": row[0],
                    "plan_id": row[1],
                    "subscription_url": row[2],
                    "created_at": row[3],
                    "service_type": row[4],
                }
    return None


# ─── Orders ──────────────────────────────────────────────────────
async def create_order(user_id: int, plan_id: str, service_type: str = "cdn") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, plan_id, service_type) VALUES (?, ?, ?)",
            (user_id, plan_id, service_type)
        )
        await db.commit()
        return cur.lastrowid


# ─── Referrals ───────────────────────────────────────────────────
async def add_referral(referrer_id: int, referred_id: int):
    """ثبت یه رفرال جدید (قبل از تأیید عضویت کانال)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO referrals (referrer_id, referred_id)
            VALUES (?, ?)
        """, (referrer_id, referred_id))
        await db.commit()


async def reward_referral(referred_id: int) -> Optional[int]:
    """
    وقتی کاربر جدید عضو کانال شد، امتیاز به referrer میده.
    اگه قبلاً جایزه داده شده یا رفرالی وجود نداره None برمیگردونه،
    در غیر اینصورت referrer_id رو برمیگردونه.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT referrer_id FROM referrals
            WHERE referred_id=? AND rewarded=0
        """, (referred_id,)) as cur:
            row = await cur.fetchone()

        if not row:
            return None

        referrer_id = row[0]

        # جلوگیری از خود-رفرال
        if referrer_id == referred_id:
            return None

        await db.execute(
            "UPDATE referrals SET rewarded=1 WHERE referred_id=?", (referred_id,)
        )
        # افزودن امتیاز
        await db.execute("""
            INSERT INTO referral_points (user_id, points, total_earned)
            VALUES (?, 1, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                points = points + 1,
                total_earned = total_earned + 1
        """, (referrer_id,))
        await db.commit()
        return referrer_id


async def get_referral_points(user_id: int) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT points, total_earned FROM referral_points WHERE user_id=?
        """, (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return {"points": row[0], "total_earned": row[1]}
    return {"points": 0, "total_earned": 0}


async def get_referral_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND rewarded=1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def spend_referral_points(user_id: int, amount: int = 5) -> bool:
    """کسر امتیاز برای دریافت سرویس رایگان"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT points FROM referral_points WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row or row[0] < amount:
            return False
        await db.execute(
            "UPDATE referral_points SET points = points - ? WHERE user_id=?",
            (amount, user_id)
        )
        await db.commit()
        return True


async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT amount FROM balance WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def add_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO balance (user_id, amount) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET amount = amount + ?
        """, (user_id, amount, amount))
        await db.commit()


async def spend_balance(user_id: int, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        # کسر اتمیک: شرط موجودی داخل خود UPDATE است تا دو درخواست همزمان دوبار خرج نکنند
        cur = await db.execute(
            "UPDATE balance SET amount = amount - ? WHERE user_id=? AND amount >= ?",
            (amount, user_id, amount))
        await db.commit()
        return cur.rowcount == 1


async def get_user_services(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT panel_username, plan_id, service_type, created_at, subscription_url
            FROM services WHERE user_id=?
            ORDER BY created_at DESC
        """, (user_id,)) as cur:
            rows = await cur.fetchall()
            return [{"panel_username": r[0], "plan_id": r[1],
                     "service_type": r[2], "created_at": r[3],
                     "subscription_url": r[4] or ""} for r in rows]



async def check_and_set_warning(user_id: int, panel_username: str, warn_type: str) -> bool:
    """True برمیگردونه اگه قبلاً هشدار داده شده، False اگه هنوز نداده"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT 1 FROM usage_warnings
            WHERE panel_username=? AND warn_type=?
        """, (panel_username, warn_type)) as cur:
            exists = await cur.fetchone()
        if exists:
            return True
        await db.execute("""
            INSERT OR IGNORE INTO usage_warnings (user_id, panel_username, warn_type)
            VALUES (?, ?, ?)
        """, (user_id, panel_username, warn_type))
        await db.commit()
        return False


async def get_all_services() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id, panel_username, plan_id, service_type
            FROM services
        """) as cur:
            rows = await cur.fetchall()
            return [{"user_id": r[0], "panel_username": r[1],
                     "plan_id": r[2], "service_type": r[3]} for r in rows]


# ─── Discount Codes ───────────────────────────────────────────────
async def create_discount_code(code: str, percent: int, max_per_user: int, expires_at: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO discount_codes (code, percent, max_per_user, expires_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (code.upper(), percent, max_per_user, expires_at))
        await db.commit()


async def get_discount_code(code: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT code, percent, max_per_user, expires_at, is_active, created_at
            FROM discount_codes WHERE code=?
        """, (code.upper(),)) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "code": row[0], "percent": row[1], "max_per_user": row[2],
                    "expires_at": row[3], "is_active": row[4], "created_at": row[5]
                }
    return None


async def get_all_discount_codes() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT code, percent, max_per_user, expires_at, is_active, created_at
            FROM discount_codes ORDER BY created_at DESC
        """) as cur:
            rows = await cur.fetchall()
            return [{
                "code": r[0], "percent": r[1], "max_per_user": r[2],
                "expires_at": r[3], "is_active": r[4], "created_at": r[5]
            } for r in rows]


async def get_user_code_usage_count(code: str, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM discount_usages WHERE code=? AND user_id=?
        """, (code.upper(), user_id)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_code_total_usage_count(code: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM discount_usages WHERE code=?
        """, (code.upper(),)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def record_discount_usage(code: str, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO discount_usages (code, user_id) VALUES (?, ?)
        """, (code.upper(), user_id))
        await db.commit()


async def deactivate_discount_code(code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE discount_codes SET is_active=0 WHERE code=?", (code.upper(),)
        )
        await db.commit()


async def delete_discount_code(code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM discount_codes WHERE code=?", (code.upper(),))
        await db.execute("DELETE FROM discount_usages WHERE code=?", (code.upper(),))
        await db.commit()


# ─── Button Emojis (ایموجی پرمیوم روی دکمه‌ها) ───────────────────
async def set_button_emoji(button_key: str, emoji_id: str, fallback: str = "😀"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO button_emojis (button_key, emoji_id, fallback)
            VALUES (?, ?, ?)
        """, (button_key, emoji_id, fallback))
        await db.commit()


async def get_button_emoji(button_key: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT emoji_id, fallback FROM button_emojis WHERE button_key=?
        """, (button_key,)) as cur:
            row = await cur.fetchone()
            if row:
                return {"emoji_id": row[0], "fallback": row[1]}
    return None


async def get_all_button_emojis() -> Dict[str, Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT button_key, emoji_id, fallback FROM button_emojis") as cur:
            rows = await cur.fetchall()
            return {r[0]: {"emoji_id": r[1], "fallback": r[2]} for r in rows}


async def remove_button_emoji(button_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM button_emojis WHERE button_key=?", (button_key,))
        await db.commit()



# ─── Pending Purchases (برای کوتاه کردن callback_data ادمین) ──────
async def save_pending_purchase(purchase_id: str, user_id: int, plan_id: str,
                                 panel_username: str, price: int,
                                 code: Optional[str], is_unlimited: bool,
                                 service_type: str = "cdn"):

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_purchases (
                purchase_id    TEXT PRIMARY KEY,
                user_id        INTEGER,
                plan_id        TEXT,
                panel_username TEXT,
                price          INTEGER,
                code           TEXT,
                is_unlimited   INTEGER,
                service_type   TEXT DEFAULT 'cdn',
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            INSERT OR REPLACE INTO pending_purchases
            (purchase_id, user_id, plan_id, panel_username, price, code, is_unlimited, service_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (purchase_id, user_id, plan_id, panel_username, price, code, int(is_unlimited), service_type))
        await db.commit()


async def get_pending_purchase(purchase_id: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        # ساخت جدول اگه نبود
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_purchases (
                purchase_id    TEXT PRIMARY KEY,
                user_id        INTEGER,
                plan_id        TEXT,
                panel_username TEXT,
                price          INTEGER,
                code           TEXT,
                is_unlimited   INTEGER,
                service_type   TEXT DEFAULT 'cdn',
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        async with db.execute(
            "SELECT user_id, plan_id, panel_username, price, code, is_unlimited, service_type "
            "FROM pending_purchases WHERE purchase_id=?", (purchase_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "user_id": row[0], "plan_id": row[1],
                    "panel_username": row[2], "price": row[3],
                    "code": row[4], "is_unlimited": bool(row[5]),
                    "service_type": row[6] or ("unlimited" if bool(row[5]) else "cdn")
                }
    return None


async def delete_pending_purchase(purchase_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_purchases WHERE purchase_id=?", (purchase_id,))
        await db.commit()

# ─── Bot Texts (ویرایش متن‌ها از پنل ادمین) ──────────────────────
async def get_text(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM bot_texts WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_text(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_texts (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()


async def get_all_texts() -> Dict[str, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM bot_texts") as cur:
            rows = await cur.fetchall()
            return {r[0]: r[1] for r in rows}
