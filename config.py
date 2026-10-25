import os
# ===== تنظیمات اصلی ربات =====

BOT_TOKEN = os.getenv("BOT_TOKEN", "8989090983:AAGm8EJOtzU8w6qmyhb3rUDAXdcdDqmIoPI")
# اطلاعات ادمین پنل مرزبان
PANEL_URL = os.getenv("PANEL_URL", "https://fardad.marzgozari.com")
PANEL_USERNAME = os.getenv("PANEL_USERNAME", "Fardad0@")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "Fardad0@")
# ─── پنل نامحدود (مرزبان جدید) ──────────────────────────────────
UNLIMITED_PANEL_URL = os.getenv("UNLIMITED_PANEL_URL", "https://fardad.marzgozari.com")
UNLIMITED_PANEL_USERNAME = os.getenv("UNLIMITED_PANEL_USERNAME", "Fardad0@")
UNLIMITED_PANEL_PASSWORD = os.getenv("UNLIMITED_PANEL_PASSWORD", "Fardad0@")
# آیدی عددی ادمین‌های ربات (می‌تونی چند تا بذاری)
ADMIN_IDS = [8612350398]

# کانال عضویت اجباری (اگه نمی‌خوای بذار None)
FORCE_JOIN_CHANNEL = "@Spider_Man_Vpn"  # یا None

# اطلاعات پرداخت
CARD_NUMBER = "6219-8619-1734-4961"
CARD_OWNER = "سیدی"

# ===== پلن‌های حجمی =====
PLANS = {
    "plan_1": {
        "name": "10 گیگ",
        "data_limit_gb": 10,
        "duration_days": 30,
        "price": 25000,
        "description": "10 گیگ • 1 ماهه",
        "emoji": "📦"
    },
    "plan_2": {
        "name": "20 گیگ",
        "data_limit_gb": 20,
        "duration_days": 30,
        "price": 50000,
        "description": "20 گیگ • 1 ماهه",
        "emoji": "📦"
    },
    "plan_3": {
        "name": "30 گیگ",
        "data_limit_gb": 30,
        "duration_days": 30,
        "price": 75000,
        "description": "30 گیگ • 1 ماهه",
        "emoji": "📦"
    },
    "plan_4": {
        "name": "40 گیگ",
        "data_limit_gb": 40,
        "duration_days": 30,
        "price": 100000,
        "description": "40 گیگ • 1 ماهه",
        "emoji": "📦"
    },
    "plan_5": {
        "name": "50 گیگ",
        "data_limit_gb": 50,
        "duration_days": 30,
        "price": 125000,
        "description": "50 گیگ • 1 ماهه",
        "emoji": "📦"
    },
  #  "plan_6": {
#        "name": "100 گیگ",
#        "data_limit_gb": 100,
#        "duration_days": 30,
#        "price": 700000,
#        "description": "100 گیگ • 1 ماهه",
#        "emoji": "📦"
#    },
}

# ===== پلن‌های نامحدود =====
UNLIMITED_PLANS = {
    # ۱ ماهه
    "unlimited_1m_1u": {"name": "۱ ماهه — ۱ کاربر", "duration_days": 30,  "price": 169000, "users": 1, "emoji": "♾️"},
    "unlimited_1m_2u": {"name": "۱ ماهه — ۲ کاربر", "duration_days": 30,  "price": 229000, "users": 2, "emoji": "♾️"},
    "unlimited_1m_3u": {"name": "۱ ماهه — ۳ کاربر", "duration_days": 30,  "price": 289000, "users": 3, "emoji": "♾️"},

    # ۲ ماهه
    "unlimited_2m_1u": {"name": "۲ ماهه — ۱ کاربر", "duration_days": 60,  "price": 319000, "users": 1, "emoji": "♾️"},
    "unlimited_2m_2u": {"name": "۲ ماهه — ۲ کاربر", "duration_days": 60,  "price": 379000, "users": 2, "emoji": "♾️"},
    "unlimited_2m_3u": {"name": "۲ ماهه — ۳ کاربر", "duration_days": 60,  "price": 439000, "users": 3, "emoji": "♾️"},

    # ۳ ماهه
    "unlimited_3m_1u": {"name": "۳ ماهه — ۱ کاربر", "duration_days": 90,  "price": 499000, "users": 1, "emoji": "♾️"},
    "unlimited_3m_2u": {"name": "۳ ماهه — ۲ کاربر", "duration_days": 90,  "price": 559000, "users": 2, "emoji": "♾️"},
    "unlimited_3m_3u": {"name": "۳ ماهه — ۳ کاربر", "duration_days": 90,  "price": 619000, "users": 3, "emoji": "♾️"},
}
# تگ اختصاصی برای شناسایی کانفیگ‌های ساخته‌شده توسط ربات
USER_TAG           = "s_l_"   # سرویس‌های حجمی
UNLIMITED_USER_TAG = "s_unl_"    # سرویس‌های نامحدود

# ─── پنل Tunnel Premium ──────────────────────────────────────────
# مقادیر واقعی را اینجا قرار بده یا در صورت استفاده از .env مطابق ساختار پروژه از env بخوان.
TUNNEL_PANEL_URL = os.getenv("TUNNEL_PANEL_URL", "https://premium.marzgozari.com")
TUNNEL_PANEL_USERNAME = os.getenv("TUNNEL_PANEL_USERNAME", "Fardad0@")
TUNNEL_PANEL_PASSWORD = os.getenv("TUNNEL_PANEL_PASSWORD", "Fardad0@")
TUNNEL_USER_TAG = "S_TUNNEL_"

# پلن‌های Tunnel Premium — مقادیر واقعی فروش را اینجا تنظیم کن.
# ساختار با PLANS یکسان است تا keyboard و flow فعلی قابل استفاده بماند.
TUNNEL_PLANS = {
    "plan_1": {
        "name": "۵ گیگ",
        "data_limit_gb": 5,
        "duration_days": 30,
        "price": 30000,
        "description": "۵ گیگ • ۱ ماهه",
        "emoji": "📦"
    },
    "plan_2": {
        "name": "۱۰ گیگ",
        "data_limit_gb": 10,
        "duration_days": 30,
        "price": 60000,
        "description": "۱۰ گیگ • ۱ ماهه",
        "emoji": "📦"
    },
    "plan_3": {
        "name": "۲۰ گیگ",
        "data_limit_gb": 20,
        "duration_days": 30,
        "price": 120000,
        "description": "۲۰ گیگ • ۱ ماهه",
        "emoji": "📦"
    },
    "plan_4": {
        "name": "۳۰ گیگ",
        "data_limit_gb": 30,
        "duration_days": 30,
        "price": 180000,
        "description": "۳۰ گیگ • ۱ ماهه",
        "emoji": "📦"
    },
    "plan_5": {
        "name": "۵۰ گیگ",
        "data_limit_gb": 50,
        "duration_days": 30,
        "price": 280000,
        "description": "۵۰ گیگ • ۱ ماهه",
        "emoji": "📦"
    },
    "plan_6": {
        "name": "۱۰۰ گیگ",
        "data_limit_gb": 100,
        "duration_days": 30,
        "price": 550000,
        "description": "۱۰۰ گیگ • ۱ ماهه",
        "emoji": "📦"
    },
    "plan_7": {
        "name": "۵۰ گیگ",
        "data_limit_gb": 50,
        "duration_days": 60,
        "price": 350000,
        "description": "۵۰ گیگ • ۲ ماهه",
        "emoji": "📦"
    },
    "plan_8": {
        "name": "۱۰۰ گیگ",
        "data_limit_gb": 100,
        "duration_days": 60,
        "price": 650000,
        "description": "۱۰۰ گیگ • ۲ ماهه",
        "emoji": "📦"
    },
}
# (نیازی به تنظیم inbound نیست - پنل نمایندگی خودکار اعمال می‌کنه)
