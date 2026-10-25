import os
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import PLANS, UNLIMITED_PLANS, TUNNEL_PLANS
import database as db

# ══════════════════════════════════════════════════════════════════
# اصول رنگ‌بندی واقعی دکمه‌ها (Bot API 9.4 - فیلد style):
#   style="success" → سبز  → تأیید / ثبت نهایی / اقدام مثبت
#   style="danger"  → قرمز → لغو / رد / پشیمونی / حذف
#   style="primary" → آبی  → اقدام عادی / انتخاب / پیمایش
#   style=None      → رنگ پیش‌فرض کلاینت (خاکستری) → بازگشت / خنثی
#
# هر دکمه یک "key" ثابت دارد که از پنل ادمین می‌توان emoji-id
# پرمیوم اختصاصی آن را تنظیم کرد (جدول button_emojis).
# ══════════════════════════════════════════════════════════════════

BUTTON_KEYS_FA = {
    "buy":                  "🛒 خرید سرویس حجمی",
    "buy_cdn":              "🟢 سرویس عادی (CDN)",
    "buy_tunnel":           "⚡️ سرویس ویژه (Tunnel Premium)",
    "buy_unlimited":        "♾️ خرید سرویس نامحدود",
    "my_account":           "👤 حساب من",
    "referral":             "🎁 رفرال و هدیه",
    "check_service":        "📊 وضعیت سرویس",
    "support":              "📞 پشتیبانی",
    "guide":                "📖 راهنما",
    "select_plan":          "📦 انتخاب پلن (هر پلن)",
    "back":                 "🔙 بازگشت",
    "confirm_purchase":     "✅ تأیید و پرداخت",
    "cancel_purchase":      "❌ انصراف خرید",
    "pay_balance":          "💰 پرداخت از موجودی",
    "pay_card":             "💳 پرداخت کارت به کارت",
    "enter_discount":       "🏷 کد تخفیف دارم",
    "paid_sent_receipt":    "✅ پرداخت کردم، ارسال رسید",
    "admin_approve":        "✅ تأیید و ساخت سرویس (ادمین)",
    "admin_reject":         "❌ رد کردن (ادمین)",
    "copy_link":            "📋 کپی لینک اتصال",
    "guide_link":           "📱 راهنمای اتصال",
    "refresh_service":      "🔄 به‌روزرسانی",
    "home":                 "🏠 منوی اصلی",
    "support_chat":         "💬 چت با پشتیبان",
    "guide_android":        "🤖 اندروید",
    "guide_ios":            "🍎 iOS",
    "guide_windows":        "🪟 ویندوز",
    "guide_mac":            "🍏 مک",
    "add_balance":          "💰 افزایش موجودی",
    "balance_paid":         "✅ پرداخت کردم (شارژ موجودی)",
    "admin_balance_approve":"✅ تأیید شارژ (ادمین)",
    "admin_balance_reject": "❌ رد شارژ (ادمین)",
    "accept_rules":         "✅ قوانین را قبول دارم",
    "decline_rules":        "❌ انصراف از قوانین",
    "claim_reward":         "🎁 دریافت سرویس رایگان",
    "confirm_claim":        "✅ بله، دریافت کن",
    "cancel_claim":         "❌ انصراف دریافت جایزه",
    "convert_all_points":   "🔄 تبدیل همه امتیازها",
    "admin_stats":          "📊 آمار سیستم",
    "admin_users":          "👥 کاربران",
    "admin_texts":          "✏️ ویرایش متن‌ها",
    "admin_broadcast":      "📢 پیام همگانی",
    "admin_discounts":      "🏷 کدهای تخفیف",
    "admin_buttons":        "🔘 ایموجی دکمه‌ها",
    "edit_text_item":       "✏️ هر آیتم ویرایش متن",
    "cancel_edit":          "❌ لغو ویرایش",
    "edit_balance":         "💰 ویرایش موجودی (ادمین)",
    "edit_points":          "⭐️ ویرایش امتیاز (ادمین)",
    "confirm_edit":         "✅ تأیید ویرایش (ادمین)",
    "cancel_user_edit":     "❌ لغو ویرایش کاربر (ادمین)",
    "new_discount":         "➕ ساخت کد تخفیف جدید",
    "view_discount_item":   "🏷 هر آیتم کد تخفیف",
    "deactivate_discount":  "⛔️ غیرفعال کردن کد",
    "delete_discount":      "🗑 حذف کد تخفیف",
    "confirm_delete_discount": "✅ تأیید حذف کد",
    "back_to_discount_list":  "🔙 بازگشت به لیست کدها",
    "back_to_admin_texts":    "🔙 بازگشت به لیست متن‌ها",
    # صفحه‌بندی سرویس‌ها
    "svc_prev_page":          "◀️ صفحه قبل",
    "svc_next_page":          "▶️ صفحه بعد",
    "svc_detail":             "🔍 جزئیات سرویس",
    # تمدید
    "renew":                  "🔄 تمدید اشتراک",
    "renew_confirm":          "✅ تأیید تمدید",
    "renew_cancel":           "❌ انصراف از تمدید",
    "renew_pay_balance":      "💰 پرداخت تمدید از موجودی",
    "renew_pay_card":         "💳 پرداخت تمدید کارت به کارت",
    "admin_renew_approve":    "✅ تأیید تمدید (ادمین)",
}


import re

# الگوی شناسایی ایموجی(ها) در ابتدای متن دکمه (شامل اموجی‌های ترکیبی/مالتی‌بایت و فاصله بعدش)
_LEADING_EMOJI_PATTERN = re.compile(
    r'^[\U0001F000-\U0001FFFF\u2190-\u21FF\u2300-\u23FF\u2460-\u27BF\u2B00-\u2BFF\u2900-\u297F\uFE0F\u200D]+\s*'
)


def _strip_leading_emoji(text: str) -> str:
    """حذف ایموجی(های) ابتدای متن - وقتی icon_custom_emoji_id ست میشه دیگه نیازی به ایموجی متنی نیست"""
    return _LEADING_EMOJI_PATTERN.sub("", text)


def btn(key, text, emoji_map=None, style=None, **kwargs):
    icon_id = None
    if emoji_map and key in emoji_map:
        icon_id = emoji_map[key]["emoji_id"]
    if icon_id:
        clean_text = _strip_leading_emoji(text)
        return InlineKeyboardButton(text=clean_text, style=style, icon_custom_emoji_id=icon_id, **kwargs)
    return InlineKeyboardButton(text=text, style=style, **kwargs)


async def get_emoji_map() -> dict:
    return await db.get_all_button_emojis()


async def main_menu_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    _wa_url = os.getenv("WEBAPP_URL", "").rstrip("/")
    if _wa_url:   # دکمه ورود به Mini App (فقط وقتی WEBAPP_URL تنظیم شده)
        builder.row(InlineKeyboardButton(text="🕸 ورود به Mini App", style="success",
                                         web_app=WebAppInfo(url=_wa_url + "/")))
    builder.row(
        btn("buy", "🛒 خرید سرویس حجمی", em, style="primary", callback_data="buy"),
        btn("my_account", "👤 حساب من", em, style="primary", callback_data="my_account")
    )
    builder.row(
        btn("buy_unlimited", "♾️ خرید سرویس نامحدود", em, style="primary", callback_data="buy_unlimited"),
        btn("check_service", "📊 وضعیت سرویس", em, style="primary", callback_data="check_service")
    )
    builder.row(
        btn("referral", "🎁 رفرال و هدیه", em, style="primary", callback_data="referral"),
        btn("support", "📞 پشتیبانی", em, style="primary", callback_data="support")
    )
    builder.row(
        btn("guide", "📖 راهنما", em, style="primary", callback_data="guide")
    )
    return builder.as_markup()


async def service_type_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("buy_cdn", "🟢 سرویس عادی (CDN)", em, style="primary", callback_data="buy_cdn"))
    builder.row(btn("buy_tunnel", "⚡️ سرویس ویژه (Tunnel Premium)", em, style="primary", callback_data="buy_tunnel"))
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


async def plans_kb(service_type: str = "cdn") -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    plans = TUNNEL_PLANS if service_type == "tunnel" else PLANS
    for plan_id, plan in plans.items():
        price_fmt = f"{plan['price']:,}"
        builder.row(
            btn("select_plan", f"{plan['emoji']} {plan['name']}  |  {price_fmt} تومان",
                em, style="primary", callback_data=f"select_plan:{service_type}:{plan_id}")
        )
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


async def confirm_purchase_kb(target: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("confirm_purchase", "✅ تأیید و پرداخت", em, style="success", callback_data=f"confirm_pay:{target}"))
    builder.row(btn("cancel_purchase", "❌ انصراف", em, style="danger", callback_data="buy"))
    return builder.as_markup()


async def payment_method_kb(target: str, can_use_balance: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    if can_use_balance:
        builder.row(btn("pay_balance", "💰 پرداخت از موجودی", em, style="primary", callback_data=f"pay_balance:{target}"))
    builder.row(btn("pay_card", "💳 پرداخت کارت به کارت", em, style="primary", callback_data=f"confirm_pay:{target}"))
    builder.row(btn("enter_discount", "🏷 کد تخفیف دارم", em, style="primary", callback_data=f"enter_discount:{target}"))
    builder.row(btn("cancel_purchase", "❌ بازگشت", em, style="danger", callback_data="buy"))
    return builder.as_markup()


async def discount_result_kb(target: str, can_use_balance: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    if can_use_balance:
        builder.row(btn("pay_balance", "💰 پرداخت از موجودی", em, style="primary", callback_data=f"pay_balance:{target}"))
    builder.row(btn("pay_card", "💳 پرداخت کارت به کارت", em, style="primary", callback_data=f"confirm_pay:{target}"))
    builder.row(btn("cancel_purchase", "❌ بازگشت", em, style="danger", callback_data="buy"))
    return builder.as_markup()


async def payment_sent_kb(target: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("paid_sent_receipt", "✅ پرداخت کردم، رسید ارسال می‌کنم", em, style="success", callback_data=f"paid:{target}"))
    builder.row(btn("cancel_purchase", "❌ بازگشت", em, style="danger", callback_data="buy"))
    return builder.as_markup()


async def admin_verify_kb(purchase_id: str) -> InlineKeyboardMarkup:
    """فقط purchase_id کوتاه — اطلاعات از دیتابیس خونده میشه"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تأیید و ساخت سرویس", style="success",
            callback_data=f"adm_ok:{purchase_id}"),
        InlineKeyboardButton(text="❌ رد کردن", style="danger",
            callback_data=f"adm_no:{purchase_id}")
    )
    return builder.as_markup()


async def admin_verify_unlimited_kb(purchase_id: str) -> InlineKeyboardMarkup:
    """نامحدود — فقط purchase_id"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تأیید و ساخت سرویس", style="success",
            callback_data=f"adm_ok:{purchase_id}"),
        InlineKeyboardButton(text="❌ رد کردن", style="danger",
            callback_data=f"adm_no:{purchase_id}")
    )
    return builder.as_markup()


async def service_info_kb(username: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("copy_link", "📋 کپی لینک اتصال", em, style="primary", callback_data=f"copy_link:{username}"))
    builder.row(
        btn("guide_link", "📱 راهنمای اتصال", em, style="primary", callback_data="guide"),
        btn("refresh_service", "🔄 به‌روزرسانی", em, style="primary", callback_data="check_service")
    )
    builder.row(btn("home", "🏠 منوی اصلی", em, callback_data="back_main"))
    return builder.as_markup()


async def support_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("support_chat", "💬 چت با پشتیبان", em, url="https://t.me/VpnSpiderMan"))
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


async def guide_os_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("guide_android", "🤖 اندروید", em, style="primary", callback_data="guide_android"),
        btn("guide_ios", "🍎 iOS", em, style="primary", callback_data="guide_ios")
    )
    builder.row(
        btn("guide_windows", "🪟 ویندوز", em, style="primary", callback_data="guide_windows"),
        btn("guide_mac", "🍏 مک", em, style="primary", callback_data="guide_mac")
    )
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


async def back_main_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("home", "🏠 منوی اصلی", em, callback_data="back_main"))
    return builder.as_markup()


async def buy_and_back_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("buy", "🛒 خرید سرویس", em, style="primary", callback_data="buy"),
        btn("home", "🏠 منوی اصلی", em, callback_data="back_main")
    )
    return builder.as_markup()


async def my_account_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("add_balance", "💰 افزایش موجودی", em, style="primary", callback_data="add_balance"),
        btn("check_service", "📊 وضعیت سرویس‌ها", em, style="primary", callback_data="check_service")
    )
    builder.row(
        btn("referral", "🎁 رفرال و هدیه", em, style="primary", callback_data="referral"),
        btn("home", "🏠 منوی اصلی", em, callback_data="back_main")
    )
    return builder.as_markup()


async def add_balance_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="my_account"))
    return builder.as_markup()


async def balance_payment_kb(amount: int) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("balance_paid", "✅ پرداخت کردم، رسید ارسال می‌کنم", em, style="success", callback_data=f"balance_paid:{amount}"))
    builder.row(btn("cancel_purchase", "❌ بازگشت", em, style="danger", callback_data="add_balance"))
    return builder.as_markup()


async def admin_verify_balance_kb(user_id: int, amount: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تأیید و افزایش موجودی", style="success",
            callback_data=f"adm_bal_ok:{user_id}:{amount}"),
        InlineKeyboardButton(text="❌ رد کردن", style="danger",
            callback_data=f"adm_bal_no:{user_id}")
    )
    return builder.as_markup()


async def rules_kb(action: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("accept_rules", "✅ قوانین را خواندم و قبول دارم", em, style="success", callback_data=f"accept_rules:{action}"))
    builder.row(btn("decline_rules", "❌ انصراف", em, style="danger", callback_data="back_main"))
    return builder.as_markup()


async def convert_points_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("convert_all_points", "🔄 تبدیل همه امتیازها به حجم", em, style="primary", callback_data="convert_all_points"))
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="referral"))
    return builder.as_markup()


async def referral_kb(has_enough_points: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    if has_enough_points:
        builder.row(btn("claim_reward", "🎁 دریافت سرویس رایگان", em, style="success", callback_data="claim_referral_reward"))
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


async def confirm_claim_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("confirm_claim", "✅ بله، دریافت کن", em, style="success", callback_data="confirm_claim"),
        btn("cancel_claim", "❌ انصراف", em, style="danger", callback_data="referral")
    )
    return builder.as_markup()




async def plans_unlimited_kb() -> InlineKeyboardMarkup:
    """کیبورد پلن‌های نامحدود"""
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    for plan_id, plan in UNLIMITED_PLANS.items():
        price_fmt = f"{plan['price']:,}"
        builder.row(
            btn("select_plan", f"{plan['emoji']} {plan['name']}  |  {price_fmt} تومان",
                em, style="primary", callback_data=f"select_unlimited_plan:{plan_id}")
        )
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


async def confirm_purchase_unlimited_kb(plan_id: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("confirm_purchase", "✅ تأیید و پرداخت", em, style="success",
                    callback_data=f"confirm_unlimited_pay:{plan_id}"))
    builder.row(btn("cancel_purchase", "❌ انصراف", em, style="danger", callback_data="buy_unlimited"))
    return builder.as_markup()


async def payment_method_unlimited_kb(plan_id: str, can_use_balance: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    if can_use_balance:
        builder.row(btn("pay_balance", "💰 پرداخت از موجودی", em, style="primary",
                        callback_data=f"pay_unlimited_balance:{plan_id}"))
    builder.row(btn("pay_card", "💳 پرداخت کارت به کارت", em, style="primary",
                    callback_data=f"confirm_unlimited_pay:{plan_id}"))
    builder.row(btn("enter_discount", "🏷 کد تخفیف دارم", em, style="primary",
                    callback_data=f"enter_unlimited_discount:{plan_id}"))
    builder.row(btn("cancel_purchase", "❌ بازگشت", em, style="danger", callback_data="buy_unlimited"))
    return builder.as_markup()


async def payment_sent_unlimited_kb(plan_id: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("paid_sent_receipt", "✅ پرداخت کردم، رسید ارسال می‌کنم", em,
                    style="success", callback_data=f"paid_unlimited:{plan_id}"))
    builder.row(btn("cancel_purchase", "❌ بازگشت", em, style="danger", callback_data="buy_unlimited"))
    return builder.as_markup()


async def admin_verify_unlimited_kb(purchase_id: str) -> InlineKeyboardMarkup:
    """نامحدود — فقط purchase_id"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تأیید و ساخت سرویس", style="success",
            callback_data=f"adm_ok:{purchase_id}"),
        InlineKeyboardButton(text="❌ رد کردن", style="danger",
            callback_data=f"adm_no:{purchase_id}")
    )
    return builder.as_markup()



# ── صفحه‌بندی سرویس‌ها ────────────────────────────────────────────
async def services_page_kb(services: list, page: int, total: int) -> InlineKeyboardMarkup:
    """
    هر صفحه ۲ سرویس + دکمه‌های ناوبری
    services: لیست ۲ سرویس صفحه جاری
    page: شماره صفحه جاری (از ۰)
    total: تعداد کل سرویس‌ها
    """
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    for svc in services:
        label = f"{'♾️' if svc['service_type']=='unlimited' else '📦'} {svc['plan_name']} | {svc['status_icon']} | {svc['expire_short']}"
        builder.row(btn("svc_detail", label, em, style="primary",
                        callback_data=f"svc_detail:{svc['panel_username']}"))
        builder.row(btn("renew", "🔄 تمدید این اشتراک", em, style="primary",
                        callback_data=f"renew_select:{svc['panel_username']}"))

    # دکمه‌های ناوبری
    nav_buttons = []
    if page > 0:
        nav_buttons.append(btn("svc_prev_page", "◀️ قبلی", em,
                               callback_data=f"svc_page:{page-1}"))
    if (page + 1) * 2 < total:
        nav_buttons.append(btn("svc_next_page", "▶️ بعدی", em,
                               callback_data=f"svc_page:{page+1}"))
    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(btn("home", "🏠 منوی اصلی", em, callback_data="back_main"))
    return builder.as_markup()


# ── کیبورد جزئیات یک سرویس ───────────────────────────────────────
async def service_detail_kb(panel_username: str, page: int) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("renew", "🔄 تمدید این اشتراک", em, style="primary",
                    callback_data=f"renew_select:{panel_username}"))
    builder.row(btn("copy_link", "📋 کپی لینک اتصال", em, style="primary",
                    callback_data=f"copy_link:{panel_username}"))
    builder.row(btn("back", "🔙 بازگشت به لیست", em,
                    callback_data=f"svc_page:{page}"))
    return builder.as_markup()


# ── انتخاب پلن تمدید (نامحدود) ───────────────────────────────────
async def renew_unlimited_plans_kb(panel_username: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    # گروه‌بندی بر اساس مدت
    groups = {
        "۱ ماهه": ["unlimited_1m_1u", "unlimited_1m_2u", "unlimited_1m_3u"],
        "۲ ماهه": ["unlimited_2m_1u", "unlimited_2m_2u", "unlimited_2m_3u"],
        "۳ ماهه": ["unlimited_3m_1u", "unlimited_3m_2u", "unlimited_3m_3u"],
    }
    from config import UNLIMITED_PLANS
    for group_name, plan_ids in groups.items():
        for pid in plan_ids:
            plan = UNLIMITED_PLANS.get(pid)
            if plan:
                builder.row(btn("select_plan",
                    f"{plan['emoji']} {plan['name']} — {plan['price']:,} تومان",
                    em, style="primary",
                    callback_data=f"renew_plan:{panel_username}:{pid}"))
    builder.row(btn("renew_cancel", "❌ انصراف", em, style="danger",
                    callback_data="check_service"))
    return builder.as_markup()


# ── تأیید و روش پرداخت تمدید ─────────────────────────────────────
async def renew_payment_kb(panel_username: str, plan_id: str, can_use_balance: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    target = f"{panel_username}:{plan_id}"
    if can_use_balance:
        builder.row(btn("renew_pay_balance", "💰 پرداخت از موجودی", em, style="primary",
                        callback_data=f"renew_pay_balance:{target}"))
    builder.row(btn("renew_pay_card", "💳 پرداخت کارت به کارت", em, style="primary",
                    callback_data=f"renew_pay_card:{target}"))
    builder.row(btn("renew_cancel", "❌ انصراف", em, style="danger",
                    callback_data="check_service"))
    return builder.as_markup()


# ── تأیید ادمین برای تمدید ───────────────────────────────────────
async def admin_verify_renew_kb(purchase_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تأیید تمدید", style="success",
            callback_data=f"adm_renew_ok:{purchase_id}"),
        InlineKeyboardButton(text="❌ رد کردن", style="danger",
            callback_data=f"adm_renew_no:{purchase_id}")
    )
    return builder.as_markup()

async def admin_panel_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("admin_stats", "📊 آمار سیستم", em, style="primary", callback_data="admin_stats"),
        btn("admin_users", "👥 کاربران", em, style="primary", callback_data="admin_users")
    )
    builder.row(
        btn("admin_texts", "✏️ ویرایش متن‌ها", em, style="primary", callback_data="admin_texts"),
        btn("admin_broadcast", "📢 پیام همگانی", em, style="primary", callback_data="admin_broadcast")
    )
    builder.row(
        btn("admin_discounts", "🏷 کدهای تخفیف", em, style="primary", callback_data="admin_discounts"),
        btn("admin_buttons", "🔘 ایموجی دکمه‌ها", em, style="primary", callback_data="admin_buttons")
    )
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="back_main"))
    return builder.as_markup()


TEXT_KEYS_FA = {
    "welcome_msg":           "👋 پیام خوش‌آمدگویی",
    "buy_msg":               "🛒 صفحه خرید پلن",
    "payment_msg":           "💳 اطلاعات پرداخت",
    "service_activated_msg": "🎉 پیام فعال‌سازی سرویس",
    "support_msg":           "📞 صفحه پشتیبانی",
    "referral_msg":          "🎁 صفحه رفرال",
}

async def admin_texts_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    for key, label in TEXT_KEYS_FA.items():
        builder.row(btn("edit_text_item", label, em, style="primary", callback_data=f"edit_text:{key}"))
    builder.row(btn("back_to_admin_texts", "🔙 بازگشت به پنل ادمین", em, callback_data="admin_panel"))
    return builder.as_markup()


async def cancel_edit_kb() -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("cancel_edit", "❌ لغو ویرایش", em, style="danger", callback_data="admin_texts"))
    return builder.as_markup()


async def admin_edit_user_kb(user_id: int) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("edit_balance", "💰 ویرایش موجودی", em, style="primary", callback_data=f"admin_edit_balance:{user_id}"),
        btn("edit_points", "⭐️ ویرایش امتیاز", em, style="primary", callback_data=f"admin_edit_points:{user_id}")
    )
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="admin_panel"))
    return builder.as_markup()


async def admin_edit_confirm_kb(user_id: int, action: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("confirm_edit", "✅ تأیید", em, style="success", callback_data=f"admin_edit_confirm:{user_id}:{action}"),
        btn("cancel_user_edit", "❌ لغو", em, style="danger", callback_data=f"admin_edit_user:{user_id}")
    )
    return builder.as_markup()


async def admin_discounts_kb(codes: list) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(btn("new_discount", "➕ ساخت کد تخفیف جدید", em, style="success", callback_data="admin_new_discount"))
    for c in codes[:15]:
        style = "success" if c["is_active"] else "danger"
        builder.row(btn("view_discount_item", f"{c['code']} — {c['percent']}٪", em, style=style,
                        callback_data=f"admin_view_discount:{c['code']}"))
    builder.row(btn("back", "🔙 بازگشت", em, callback_data="admin_panel"))
    return builder.as_markup()


async def admin_discount_detail_kb(code: str, is_active: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.row(btn("deactivate_discount", "⛔️ غیرفعال کردن", em, style="danger", callback_data=f"admin_deactivate_discount:{code}"))
    builder.row(btn("delete_discount", "🗑 حذف کامل", em, style="danger", callback_data=f"admin_delete_discount:{code}"))
    builder.row(btn("back_to_discount_list", "🔙 بازگشت به لیست", em, callback_data="admin_discounts"))
    return builder.as_markup()


async def admin_confirm_delete_discount_kb(code: str) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    builder.row(
        btn("confirm_delete_discount", "✅ بله، حذف کن", em, style="success", callback_data=f"admin_confirm_delete_discount:{code}"),
        btn("cancel_user_edit", "❌ انصراف", em, style="danger", callback_data=f"admin_view_discount:{code}")
    )
    return builder.as_markup()


async def admin_buttons_list_kb(page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    keys = list(BUTTON_KEYS_FA.items())
    start = page * per_page
    chunk = keys[start:start + per_page]
    for key, label in chunk:
        has_emoji = "🟢" if key in em else "⚪️"
        builder.row(InlineKeyboardButton(text=f"{has_emoji} {label}", callback_data=f"admin_set_button_emoji:{key}"))
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"admin_buttons_page:{page-1}"))
    if start + per_page < len(keys):
        nav_row.append(InlineKeyboardButton(text="➡️ بعدی", callback_data=f"admin_buttons_page:{page+1}"))
    if nav_row:
        builder.row(*nav_row)
    builder.row(btn("back", "🔙 بازگشت به پنل ادمین", em, callback_data="admin_panel"))
    return builder.as_markup()


async def admin_button_emoji_detail_kb(key: str, has_emoji: bool) -> InlineKeyboardMarkup:
    em = await get_emoji_map()
    builder = InlineKeyboardBuilder()
    if has_emoji:
        builder.row(btn("delete_discount", "🗑 حذف ایموجی این دکمه", em, style="danger",
                        callback_data=f"admin_remove_button_emoji:{key}"))
    builder.row(btn("back_to_discount_list", "🔙 بازگشت به لیست", em, callback_data="admin_buttons"))
    return builder.as_markup()
