import hashlib
import os

from config import BOT_TOKEN

# آدرس عمومی HTTPS مینی‌اپ (دامنه Railway یا دامنه اختصاصی). اگر خالی باشد دکمه Mini App در ربات نشان داده نمی‌شود.
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
# Railway متغیر PORT را خودش می‌دهد
PORT = int(os.getenv("PORT", "8080"))
HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# اگر WEBAPP_ENABLED=0 باشد فقط ربات اجرا می‌شود
ENABLED = os.getenv("WEBAPP_ENABLED", "1") != "0"

SESSION_SECRET = os.getenv("WEBAPP_SESSION_SECRET") or hashlib.sha256(
    ("spider-webapp-session:" + BOT_TOKEN).encode()).hexdigest()
INITDATA_MAX_AGE = int(os.getenv("INITDATA_MAX_AGE", "3600"))   # حداکثر عمر auth_date
SESSION_TTL = int(os.getenv("SESSION_TTL", str(12 * 3600)))     # عمر نشست
USAGE_TTL = int(os.getenv("USAGE_TTL", "30"))                   # کش مصرف (ثانیه)
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/VpnSpiderMan")
MAX_RECEIPT_BYTES = 5 * 1024 * 1024

# تلاش مجدد فعال‌سازی: فاصله‌ها (ثانیه) و سقف تلاش
RETRY_BACKOFF = [30, 120, 600, 1800, 7200]
MAX_PROVISION_ATTEMPTS = 8
PROVISION_LOCK_SECONDS = 180   # اگر پروسه وسط فعال‌سازی مرد، بعد از این مدت دوباره claim می‌شود
WORKER_INTERVAL = 20
