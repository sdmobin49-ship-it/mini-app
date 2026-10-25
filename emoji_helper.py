import re

# الگوی شناسایی emoji-id خام که ادمین داخل متن‌ها می‌نویسه
# فرمت ورودی ادمین: {{emoji:5368324170671202286:😀}}
# اگه فقط عدد بدون ایموجی fallback بدن، 😀 پیش‌فرض استفاده میشه
EMOJI_PATTERN = re.compile(r"\{\{emoji:(\d+)(?::(.+?))?\}\}")


def render_custom_emojis(text: str) -> str:
    """
    تبدیل {{emoji:ID}} یا {{emoji:ID:🔥}} نوشته‌شده توسط ادمین در متن پیام‌ها
    به تگ HTML واقعی <tg-emoji emoji-id="ID">fallback</tg-emoji>
    این تگ فقط در parse_mode=HTML کار می‌کند.
    """
    if not text:
        return text

    def replace(match):
        emoji_id = match.group(1)
        fallback = match.group(2) or "😀"
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

    return EMOJI_PATTERN.sub(replace, text)


def extract_emoji_id(text: str):
    """
    اگه متن یک {{emoji:ID}} داشته باشه، فقط ID رو برمی‌گردونه (برای استفاده در دکمه‌ها).
    دکمه‌ها فقط از icon_custom_emoji_id (یک رشته عددی، نه تگ HTML) پشتیبانی می‌کنن
    و طبق محدودیت تلگرام فقط یک ایموجی پرمیوم در هر دکمه قابل استفاده‌ست.
    """
    if not text:
        return None
    match = EMOJI_PATTERN.search(text)
    return match.group(1) if match else None


def extract_emoji_from_message(message):
    """
    وقتی ادمین مستقیماً یک ایموجی پرمیوم را در پیام تایپ/ارسال می‌کند،
    تلگرام آن را در message.entities با type='custom_emoji' برمی‌گرداند.
    این تابع اولین custom_emoji_id موجود در پیام و خود ایموجی متنی را برمی‌گرداند.
    خروجی: (emoji_id, fallback_emoji_text) یا (None, None)
    """
    entities = message.entities or message.caption_entities or []
    text = message.text or message.caption or ""
    for ent in entities:
        if getattr(ent, "type", None) == "custom_emoji" and getattr(ent, "custom_emoji_id", None):
            fallback = text[ent.offset: ent.offset + ent.length]
            return ent.custom_emoji_id, fallback or "😀"
    return None, None


def strip_emoji_tags(text: str) -> str:
    """حذف کامل {{emoji:...}} از متن - برای استفاده در متن ساده دکمه‌ها"""
    if not text:
        return text
    return EMOJI_PATTERN.sub("", text).strip()
