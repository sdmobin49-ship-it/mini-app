import logging
import random
import string
from datetime import datetime, timezone, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

import marzban
import marzban_tunnel
import marzban_unlimited
import database as db
from emoji_helper import render_custom_emojis, extract_emoji_from_message, extract_emoji_id
from keyboards import (
    main_menu_kb, plans_kb, service_type_kb, confirm_purchase_kb,
    payment_method_kb, discount_result_kb, payment_sent_kb,
    admin_verify_kb, service_info_kb, support_kb, guide_os_kb,
    back_main_kb, buy_and_back_kb, admin_panel_kb,
    admin_texts_kb, cancel_edit_kb, TEXT_KEYS_FA,
    referral_kb, confirm_claim_kb,
    my_account_kb, add_balance_kb, balance_payment_kb,
    admin_verify_balance_kb,
    rules_kb,
    admin_edit_user_kb, admin_edit_confirm_kb,
    admin_discounts_kb, admin_discount_detail_kb, admin_confirm_delete_discount_kb,
    admin_buttons_list_kb, admin_button_emoji_detail_kb, BUTTON_KEYS_FA,
    plans_unlimited_kb, confirm_purchase_unlimited_kb,
    payment_method_unlimited_kb, payment_sent_unlimited_kb,
    admin_verify_unlimited_kb,
    services_page_kb, service_detail_kb,
    renew_unlimited_plans_kb, renew_payment_kb, admin_verify_renew_kb,
)
from config import PLANS, UNLIMITED_PLANS, TUNNEL_PLANS, ADMIN_IDS, CARD_NUMBER, CARD_OWNER, FORCE_JOIN_CHANNEL, USER_TAG, UNLIMITED_USER_TAG, TUNNEL_USER_TAG

from core_helpers import (
    bytes_to_gb, parse_expire, format_expire, days_remaining,
    panel_for_username, get_discount_for_user, apply_discount,
)

router = Router()
logger = logging.getLogger(__name__)

TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

POINTS_PER_REWARD = 3
REWARD_DAYS       = 30

RULES_TEXT = """⚠️ <b>قوانین استفاده از سرویس</b>

لطفاً قبل از دریافت سرویس، قوانین زیر را با دقت بخوانید:

🚫 <b>موارد ممنوع:</b>
  • اشتراک‌گذاری لینک سابسکریپشن یا کانفیگ در کانال‌ها و گروه‌های عمومی
  • ارسال لینک یا کانفیگ از طریق اپ‌های ایرانی (بله، ایتا، روبیکا و...)
  • ارسال لینک یا کانفیگ از طریق SMS
  • فروش یا واگذاری سرویس به دیگران

❌ <b>تبعات نقض قوانین:</b>
  بن شدن کامل و دائمی اکانت بدون امکان بازگشت وجه

✅ با زدن دکمه «قبول دارم» تأیید می‌کنید که قوانین را خوانده و می‌پذیرید."""


# ══════════════════════════════════════════════════════════════════
#  States
# ══════════════════════════════════════════════════════════════════
class PurchaseState(StatesGroup):
    waiting_receipt = State()


class RenewState(StatesGroup):
    waiting_receipt = State()


class BalanceState(StatesGroup):
    waiting_amount  = State()
    waiting_receipt = State()


class DiscountState(StatesGroup):
    waiting_code = State()


class AdminState(StatesGroup):
    broadcast_message    = State()
    editing_text_val      = State()
    edit_user_balance     = State()
    new_discount_code     = State()
    new_discount_percent  = State()
    new_discount_limit    = State()
    new_discount_days     = State()
    setting_button_emoji  = State()


# ══════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════
def generate_username() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{USER_TAG}{suffix}"


def generate_unlimited_username() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{UNLIMITED_USER_TAG}{suffix}"


def generate_tunnel_username() -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{TUNNEL_USER_TAG}{suffix}"












def progress_bar(used: float, total: float) -> str:
    if total == 0:
        return "∞"
    pct = min(used / total, 1.0)
    filled = int(pct * 10)
    return f"{'█'*filled}{'░'*(10-filled)} {pct*100:.0f}%"


async def get_text(key: str) -> str:
    val = await db.get_text(key)
    raw = val or f"[متن {key} تنظیم نشده]"
    return render_custom_emojis(raw)


async def check_membership(bot: Bot, user_id: int) -> bool:
    if not FORCE_JOIN_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return True


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id=chat_id, text=render_custom_emojis(text), **kwargs)
    except TelegramBadRequest as e:
        logger.error(f"safe_send error to {chat_id}: {e}")


async def safe_edit(message, text: str, **kwargs):
    try:
        await message.edit_text(render_custom_emojis(text), **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def safe_edit_caption(message, caption: str, **kwargs):
    try:
        await message.edit_caption(render_custom_emojis(caption), **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.error(f"safe_edit_caption error: {e}")






# ══════════════════════════════════════════════════════════════════
#  هشدار مصرف (scheduler)
# ══════════════════════════════════════════════════════════════════
async def check_usage_warnings(bot: Bot):
    try:
        all_services = await db.get_all_services()
        for svc in all_services:
            user_id  = svc["user_id"]
            uname    = svc["panel_username"]
            if svc["service_type"] == "unlimited":
                continue
            plan_map = TUNNEL_PLANS if svc["service_type"] == "tunnel" else PLANS
            plan     = plan_map.get(svc["plan_id"], {})
            try:
                panel = marzban_tunnel if svc["service_type"] == "tunnel" else marzban
                user_data = await panel.get_user(uname)
            except Exception:
                continue
            if not user_data or user_data.get("status") != "active":
                continue

            total_gb = plan.get("data_limit_gb") or bytes_to_gb(user_data.get("data_limit", 0))
            if not total_gb:
                continue

            used_gb   = bytes_to_gb(user_data.get("used_traffic", 0))
            expire_ts = user_data.get("expire", 0)
            days_left = days_remaining(expire_ts)

            if total_gb > 0 and (used_gb / total_gb) >= 0.8:
                warned = await db.check_and_set_warning(user_id, uname, "traffic")
                if not warned:
                    await safe_send(
                        bot, user_id,
                        f"⚠️ <b>هشدار مصرف حجم</b>\n\n"
                        f"شما <b>{used_gb} GB</b> از <b>{total_gb} GB</b> را مصرف کرده‌اید.\n"
                        f"{progress_bar(used_gb, total_gb)}\n\n"
                        f"حجم سرویس شما رو به اتمام است.\n"
                        f"برای تمدید یا خرید سرویس جدید اقدام کنید 👇",
                        reply_markup=await buy_and_back_kb(), parse_mode="HTML"
                    )

            plan_days = plan.get("duration_days", 30)
            if expire_ts and days_left <= int(plan_days * 0.2):
                warned = await db.check_and_set_warning(user_id, uname, "expire")
                if not warned:
                    await safe_send(
                        bot, user_id,
                        f"⏰ <b>هشدار انقضای سرویس</b>\n\n"
                        f"سرویس شما <b>{days_left} روز</b> دیگر منقضی می‌شود.\n"
                        f"تاریخ انقضا: <b>{format_expire(expire_ts)}</b>\n\n"
                        f"برای تمدید سرویس اقدام کنید 👇",
                        reply_markup=await buy_and_back_kb(), parse_mode="HTML"
                    )
    except Exception as e:
        logger.error(f"check_usage_warnings error: {e}")


# ══════════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════════
@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    await db.init_db()
    user_id = message.from_user.id
    is_new  = not await db.user_exists(user_id)

    args        = message.text.split()
    referred_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referred_by = int(args[1][4:])
            if referred_by == user_id:
                referred_by = None
        except ValueError:
            referred_by = None

    await db.save_user(user_id, message.from_user.username or "",
                       message.from_user.full_name, referred_by=referred_by)

    if is_new and referred_by:
        await db.add_referral(referred_by, user_id)

    if not await check_membership(bot, user_id):
        await message.answer(
            f"⚠️ برای استفاده از ربات باید عضو کانال ما بشی:\n"
            f"{FORCE_JOIN_CHANNEL}\n\nبعد از عضویت دوباره /start بزن."
        )
        return

    referrer = await db.reward_referral(user_id)
    if referrer:
        pts = await db.get_referral_points(referrer)
        await safe_send(
            bot, referrer,
            f"🎉 یه نفر با لینک دعوت تو عضو شد!\n\n"
            f"⭐️ امتیاز فعلی تو: <b>{pts['points']}</b>\n"
            f"هر {POINTS_PER_REWARD} امتیاز = ۱ گیگ سرویس رایگان 🎁",
            parse_mode="HTML"
        )

    name = message.from_user.first_name
    text = (await get_text("welcome_msg")).replace("{name}", name)
    await message.answer(text, reply_markup=await main_menu_kb(), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
#  منوی اصلی
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery):
    name = call.from_user.first_name
    await safe_edit(call.message,
        f"🏠 <b>منوی اصلی</b>\n\nسلام {name}، چه کاری برات انجام بدم؟",
        reply_markup=await main_menu_kb(), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
#  حساب من — پروفایل
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "my_account")
async def my_account(call: CallbackQuery):
    user_id  = call.from_user.id
    balance  = await db.get_balance(user_id)
    pts_data = await db.get_referral_points(user_id)
    refs     = await db.get_referral_count(user_id)
    services = await db.get_user_services(user_id)

    service_lines = ""
    if services:
        for s in services[:5]:
            plan_map = UNLIMITED_PLANS if s["service_type"] == "unlimited" else TUNNEL_PLANS if s["service_type"] == "tunnel" else PLANS
            plan  = plan_map.get(s["plan_id"], {})
            pname = plan.get("name") or ("🎁 جایزه رفرال" if s["service_type"] == "free" else "سفارشی")
            stype = "♾️" if s["service_type"] == "unlimited" else "⚡️" if s["service_type"] == "tunnel" else "🎁" if s["service_type"] == "free" else "💳"
            service_lines += f"  {stype} {pname} — <code>{s['panel_username']}</code>\n"
        if len(services) > 5:
            service_lines += f"  و {len(services)-5} سرویس دیگر...\n"
    else:
        service_lines = "  ❌ سرویس فعالی نداری\n"

    text = (
        f"👤 <b>پروفایل کاربری</b>\n\n"
        f"🆔 آیدی: <code>{user_id}</code>\n"
        f"👤 نام: {call.from_user.full_name}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 موجودی کیف پول: <b>{balance:,} تومان</b>\n"
        f"⭐️ امتیاز رفرال: <b>{pts_data['points']}</b>\n"
        f"👥 تعداد دعوت‌شدگان: <b>{refs} نفر</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📦 <b>سرویس‌های من ({len(services)} عدد):</b>\n"
        f"{service_lines}"
    )
    await safe_edit(call.message, text, reply_markup=await my_account_kb(), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
#  وضعیت سرویس
# ══════════════════════════════════════════════════════════════════
#  وضعیت سرویس‌ها — صفحه‌بندی
# ══════════════════════════════════════════════════════════════════
async def _build_service_page(user_id: int, page: int):
    """ساخت داده‌های صفحه‌بندی سرویس‌ها"""
    services_raw = await db.get_user_services(user_id)
    total = len(services_raw)
    if total == 0:
        return [], 0, 0
    page = max(0, min(page, (total - 1) // 2))
    page_services = services_raw[page*2 : page*2 + 2]

    enriched = []
    for svc in page_services:
        is_unl = svc["panel_username"].startswith(UNLIMITED_USER_TAG)
        is_tunnel = svc["panel_username"].startswith(TUNNEL_USER_TAG)
        plan_map = UNLIMITED_PLANS if is_unl else TUNNEL_PLANS if (is_tunnel or svc["service_type"] == "tunnel") else PLANS
        plan = plan_map.get(svc["plan_id"], {})
        try:
            panel = marzban_unlimited if is_unl else marzban_tunnel if is_tunnel else marzban
            ud = await panel.get_user(svc["panel_username"])
        except Exception:
            ud = None
        if ud:
            status      = ud.get("status", "unknown")
            status_icon = "🟢" if status == "active" else "🔴"
            expire_ts   = ud.get("expire", 0)
            expire_short = format_expire(expire_ts).split(" - ")[0] if expire_ts else "نامحدود"
            used_gb     = bytes_to_gb(ud.get("used_traffic", 0))
            if is_unl:
                total_gb = 0
                bar      = "∞ نامحدود"
            else:
                total_gb = plan.get("data_limit_gb") or bytes_to_gb(ud.get("data_limit", 0))
                bar      = progress_bar(used_gb, total_gb)
            sub_url = svc.get("subscription_url", "")
        else:
            status_icon  = "⚠️"
            expire_short = "خطا"
            used_gb      = 0
            total_gb     = 0
            bar          = "⚠️ خطا"
            sub_url      = svc.get("subscription_url", "")
        enriched.append({
            "panel_username": svc["panel_username"],
            "plan_id":        svc["plan_id"],
            "plan_name":      plan.get("name", svc["plan_id"]),
            "service_type":   svc["service_type"],
            "status_icon":    status_icon,
            "expire_short":   expire_short,
            "sub_url":        sub_url,
            "used_gb":        used_gb,
            "total_gb":       total_gb,
            "bar":            bar,
            "is_unlimited":   is_unl,
        })
    return enriched, page, total


async def _show_services_page(call: CallbackQuery, page: int):
    user_id  = call.from_user.id
    enriched, cur_page, total = await _build_service_page(user_id, page)
    if not enriched:
        await safe_edit(call.message,
            "📊 <b>سرویس‌های من</b>\n\n❌ هنوز سرویس فعالی نداری.\nبرای خرید روی دکمه زیر بزن 👇",
            reply_markup=await buy_and_back_kb(), parse_mode="HTML")
        return
    now   = datetime.now(tz=TEHRAN_TZ).strftime("%H:%M:%S")
    pages = (total - 1) // 2 + 1
    lines = [f"📊 <b>سرویس‌های من</b> — صفحه {cur_page+1} از {pages}\n"]
    for svc in enriched:
        type_icon = "♾️" if svc["is_unlimited"] else "⚡️" if svc["service_type"] == "tunnel" else "📦"
        lines.append(
            f"{type_icon} <b>{svc['plan_name']}</b>\n"
            f"🔑 <code>{svc['panel_username']}</code>\n"
            f"{svc['status_icon']} انقضا: {svc['expire_short']}\n"
            f"{svc['bar']}\n"
        )
    lines.append(f"\n🕐 {now}")
    await safe_edit(call.message, "\n".join(lines),
        reply_markup=await services_page_kb(enriched, cur_page, total),
        parse_mode="HTML")


@router.callback_query(F.data == "check_service")
async def check_service(call: CallbackQuery):
    await call.answer("🔄 در حال بروزرسانی...")
    await _show_services_page(call, 0)


@router.callback_query(F.data.startswith("svc_page:"))
async def svc_page(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    await _show_services_page(call, page)


@router.callback_query(F.data.startswith("svc_detail:"))
async def svc_detail(call: CallbackQuery):
    panel_username = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    services_raw = await db.get_user_services(user_id)

    page = 0
    for i, s in enumerate(services_raw):
        if s["panel_username"] == panel_username:
            page = i // 2
            break

    is_unl = panel_username.startswith(UNLIMITED_USER_TAG)
    is_tunnel = panel_username.startswith(TUNNEL_USER_TAG)

    try:
        panel = (
            marzban_unlimited
            if is_unl
            else marzban_tunnel
            if is_tunnel
            else marzban
        )

        ud = await panel.get_user(panel_username)

    except Exception:
        ud = None

    if not ud:
        await call.answer(
            "خطا در دریافت اطلاعات از پنل",
            show_alert=True
        )
        return

    svc = next(
        (s for s in services_raw if s["panel_username"] == panel_username),
        {}
    )

    plan_id = svc.get("plan_id", "")
    service_type = svc.get("service_type", "")

    # انتخاب پلن بر اساس نوع سرویس
    if service_type == "tunnel" or is_tunnel:
        plan = TUNNEL_PLANS.get(plan_id, {})
    elif service_type == "unlimited" or is_unl:
        plan = UNLIMITED_PLANS.get(plan_id, {})
    else:
        plan = PLANS.get(plan_id, {})

    used = bytes_to_gb(ud.get("used_traffic", 0))
    expire_ts = ud.get("expire", 0)
    status = ud.get("status", "unknown")
    status_ico = "🟢" if status == "active" else "🔴"
    sub_url = svc.get("subscription_url", "")

    if is_unl or service_type == "unlimited":
        usage_line = (
            f"💾 مصرف: {used} GB از ∞\n"
            f"∞ نامحدود"
        )
    else:
        tgb = (
            plan.get("data_limit_gb")
            or bytes_to_gb(ud.get("data_limit", 0))
        )

        usage_line = (
            f"💾 مصرف: {used} GB از {tgb} GB\n"
            f"{progress_bar(used, tgb)}"
        )

    text = (
        f"📋 <b>جزئیات سرویس</b>\n\n"
        f"📦 پلن: {plan.get('name', '-')}\n"
        f"🔑 یوزرنیم: <code>{panel_username}</code>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{status_ico} وضعیت: "
        f"{'فعال' if status == 'active' else 'غیرفعال'}\n"
        f"{usage_line}\n"
        f"📅 انقضا: {format_expire(expire_ts)}\n\n"
        f"🔗 <b>لینک اشتراک:</b>\n"
        f"<code>{sub_url}</code>"
    )

    await safe_edit(
        call.message,
        text,
        reply_markup=await service_detail_kb(
            panel_username,
            page
        ),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("copy_link:"))
async def copy_link(call: CallbackQuery):
    panel_username = call.data.split(":", 1)[1]
    services = await db.get_user_services(call.from_user.id)
    svc = next((s for s in services if s["panel_username"] == panel_username), None)
    if not svc or not svc.get("subscription_url"):
        await call.answer("لینک اشتراک پیدا نشد!", show_alert=True)
        return
    await call.message.answer(
        f"🔗 <b>لینک اشتراک:</b>\n\n"
        f"<code>{svc['subscription_url']}</code>\n\n"
        f"👆 روی لینک بزن تا کپی بشه.",
        parse_mode="HTML"
    )
    await call.answer("لینک ارسال شد ✅")


# ══════════════════════════════════════════════════════════════════
#  افزایش موجودی
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "add_balance")
async def add_balance_menu(call: CallbackQuery, state: FSMContext):
    balance = await db.get_balance(call.from_user.id)
    await state.set_state(BalanceState.waiting_amount)
    await safe_edit(call.message,
        f"💰 <b>افزایش موجودی</b>\n\n"
        f"موجودی فعلی: <b>{balance:,} تومان</b>\n\n"
        f"مبلغ مورد نظر رو به تومان وارد کن:\n"
        f"<i>مثال: 150000</i>",
        reply_markup=await add_balance_kb(), parse_mode="HTML")


@router.message(BalanceState.waiting_amount, F.text)
async def balance_amount_entered(message: Message, state: FSMContext):
    text = message.text.replace(",", "").replace("،", "").strip()
    if not text.isdigit():
        await message.answer("⚠️ لطفاً فقط عدد وارد کن:", reply_markup=await add_balance_kb())
        return
    amount = int(text)
    if amount < 10000:
        await message.answer("⚠️ حداقل مبلغ ۱۰,۰۰۰ تومانه:", reply_markup=await add_balance_kb())
        return
    await state.update_data(balance_amount=amount)
    await state.set_state(BalanceState.waiting_receipt)
    await message.answer(
        f"💳 <b>پرداخت {amount:,} تومان</b>\n\n"
        f"شماره کارت:\n<code>{CARD_NUMBER}</code>\n\n"
        f"به نام: <b>{CARD_OWNER}</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"بعد از واریز، تصویر رسید رو ارسال کن.",
        reply_markup=await balance_payment_kb(amount), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("balance_paid:"))
async def balance_paid(call: CallbackQuery, state: FSMContext):
    amount = int(call.data.split(":")[1])
    await state.update_data(balance_amount=amount)
    await state.set_state(BalanceState.waiting_receipt)
    await safe_edit(call.message, "📸 تصویر رسید واریز رو ارسال کن:")


@router.message(BalanceState.waiting_receipt, F.photo)
async def balance_receipt(message: Message, state: FSMContext, bot: Bot):
    data   = await state.get_data()
    amount = data.get("balance_amount", 0)
    await state.clear()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=message.photo[-1].file_id,
                caption=(
                    f"💰 <b>درخواست افزایش موجودی</b>\n\n"
                    f"👤 کاربر: <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>\n"
                    f"🆔 آیدی: <code>{message.from_user.id}</code>\n"
                    f"💵 مبلغ: <b>{amount:,} تومان</b>"
                ),
                reply_markup=await admin_verify_balance_kb(message.from_user.id, amount),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending balance receipt to admin: {e}")
    await message.answer(
        "✅ رسید دریافت شد!\n⏳ بعد از تأیید ادمین موجودیت شارژ میشه.",
        reply_markup=await back_main_kb()
    )


@router.callback_query(F.data.startswith("adm_bal_ok:"))
async def admin_balance_approve(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return
    parts = call.data.split(":")
    _, user_id_s, amount_s = parts[0], parts[1], parts[2]
    user_id = int(user_id_s)
    amount  = int(amount_s)
    await db.add_balance(user_id, amount)
    new_bal = await db.get_balance(user_id)
    await safe_send(bot, user_id,
        f"✅ <b>موجودی شارژ شد!</b>\n\n"
        f"💵 مبلغ افزوده: <b>{amount:,} تومان</b>\n"
        f"💰 موجودی فعلی: <b>{new_bal:,} تومان</b>",
        parse_mode="HTML", reply_markup=await main_menu_kb())
    await safe_edit_caption(call.message,
        call.message.caption + f"\n\n✅ تأیید شد — {amount:,} تومان افزوده شد",
        parse_mode="HTML")
    await call.message.answer(
        f"✅ موجودی کاربر <code>{user_id}</code> با موفقیت {amount:,} تومان افزایش یافت.",
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("adm_bal_no:"))
async def admin_balance_reject(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    await safe_send(bot, user_id,
        "❌ درخواست افزایش موجودی تأیید نشد.\nدر صورت مشکل با پشتیبانی تماس بگیرید.",
        reply_markup=await support_kb())
    await safe_edit_caption(call.message,
        call.message.caption + "\n\n❌ رد شد", parse_mode="HTML")
    await call.message.answer(
        f"❌ درخواست شارژ کاربر <code>{user_id}</code> رد شد.",
        parse_mode="HTML"
    )


# ══════════════════════════════════════════════════════════════════
#  خرید سرویس
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "buy")
async def show_service_types(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(
        call.message,
        "🛒 <b>خرید سرویس حجمی</b>\n\nنوع سرویس رو انتخاب کن 👇",
        reply_markup=await service_type_kb(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.in_({"buy_cdn", "buy_tunnel"}))
async def select_service_type(call: CallbackQuery, state: FSMContext):
    service_type = "tunnel" if call.data == "buy_tunnel" else "cdn"
    plans = TUNNEL_PLANS if service_type == "tunnel" else PLANS
    await state.clear()
    await state.update_data(service_type=service_type)
    if not plans:
        await call.answer("هنوز پلنی برای این سرویس تنظیم نشده است.", show_alert=True)
        return
    title = "⚡️ <b>پلن‌های Tunnel Premium</b>" if service_type == "tunnel" else "🟢 <b>پلن‌های سرویس عادی (CDN)</b>"
    await safe_edit(call.message, title + "\n\nپلن موردنظرت رو انتخاب کن 👇",
                    reply_markup=await plans_kb(service_type), parse_mode="HTML")


@router.callback_query(F.data.startswith("select_plan:"))
async def select_plan(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":", 2)
    if len(parts) == 3:
        service_type, plan_id = parts[1], parts[2]
    else:
        service_type, plan_id = "cdn", parts[1]
    if service_type not in ("cdn", "tunnel"):
        await call.answer("نوع سرویس نامعتبر است!", show_alert=True)
        return
    plan = (TUNNEL_PLANS if service_type == "tunnel" else PLANS).get(plan_id)
    if not plan:
        await call.answer("پلن پیدا نشد!", show_alert=True)
        return
    await state.clear()
    await state.update_data(service_type=service_type, plan_id=plan_id)
    balance = await db.get_balance(call.from_user.id)
    can_use_balance = balance >= plan["price"]
    text = (
        f"🧾 <b>جزئیات پلن {plan['name']}</b>\n\n"
        f"📦 حجم: <b>{plan['data_limit_gb']} گیگابایت</b>\n"
        f"📅 مدت: <b>{plan['duration_days']} روز</b>\n"
        f"💰 قیمت: <b>{plan['price']:,} تومان</b>\n"
        f"👛 موجودی شما: <b>{balance:,} تومان</b>\n\n"
        f"روش پرداخت رو انتخاب کن:"
    )
    await safe_edit(call.message, text,
        reply_markup=await payment_method_kb(f"{service_type}:{plan_id}", can_use_balance),
        parse_mode="HTML")

# ── کد تخفیف ────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("enter_discount:"))
async def enter_discount_start(call: CallbackQuery, state: FSMContext):
    raw_target = call.data.split(":", 1)[1]
    parts = raw_target.split(":", 1)

    if len(parts) == 2 and parts[0] in ("cdn", "tunnel", "unlimited"):
        service_type = parts[0]
        plan_id = parts[1]
    else:
        service_type = "cdn"
        plan_id = raw_target

    await state.clear()
    await state.update_data(
        discount_plan_id=plan_id,
        service_type=service_type,
        discount_mode="unlimited" if service_type == "unlimited" else "limited"
    )

    await state.set_state(DiscountState.waiting_code)

    await safe_edit(
        call.message,
        "🏷 <b>کد تخفیف</b>\n\nکد تخفیف خودت رو وارد کن:",
        reply_markup=await back_main_kb()
    )

@router.message(DiscountState.waiting_code, F.text)
async def discount_code_entered(message: Message, state: FSMContext):
    data = await state.get_data()

    plan_id = data.get("discount_plan_id")
    service_type = data.get("service_type", "cdn")
    discount_mode = data.get("discount_mode", "limited")

    # تشخیص نوع سرویس
    if discount_mode == "unlimited":
        service_type = "unlimited"

    # انتخاب پلن متناسب با نوع سرویس
    if service_type == "unlimited":
        plan = UNLIMITED_PLANS.get(plan_id)
    elif service_type == "tunnel":
        plan = TUNNEL_PLANS.get(plan_id)
    else:
        plan = PLANS.get(plan_id)

    if not plan:
        await state.clear()
        await message.answer(
            "❌ پلن پیدا نشد. لطفاً دوباره از منوی خرید شروع کن.",
            reply_markup=await back_main_kb()
        )
        return

    code = message.text.strip().upper()

    ok, err_msg, percent = await get_discount_for_user(
        code,
        message.from_user.id
    )

    if not ok:
        await state.clear()
        await message.answer(
            err_msg,
            reply_markup=await back_main_kb()
        )
        return

    discounted_price = apply_discount(plan["price"], percent)

    balance = await db.get_balance(message.from_user.id)
    can_use_balance = balance >= discounted_price

    target = f"{service_type}:{plan_id}|{code}"
    is_unlimited = service_type == "unlimited"

    text = (
        f"✅ <b>کد تخفیف اعمال شد!</b>\n\n"
        f"🏷 کد: <code>{code}</code>\n"
        f"📉 درصد تخفیف: <b>{percent}٪</b>\n\n"
        f"📦 پلن: {plan['name']}\n"
        f"💰 قیمت اصلی: <s>{plan['price']:,} تومان</s>\n"
        f"💸 قیمت با تخفیف: <b>{discounted_price:,} تومان</b>\n\n"
        f"روش پرداخت رو انتخاب کن:"
    )

    await state.clear()

    if is_unlimited:
        kb = await payment_method_unlimited_kb(
            target,
            can_use_balance
        )
    else:
        kb = await discount_result_kb(
            target,
            can_use_balance
        )

    await message.answer(
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )


def parse_target(target: str):
    """
    target:
    service_type:plan_id|DISCOUNT_CODE

    مثال:
    cdn:plan_1|WELCOME20
    tunnel:plan_1|WELCOME20
    unlimited:plan_1|WELCOME20

    فرمت قدیمی:
    plan_id|DISCOUNT_CODE
    """

    code = None

    if "|" in target:
        target, code = target.split("|", 1)

    if ":" in target:
        service_type, plan_id = target.split(":", 1)

        if service_type in ("cdn", "tunnel", "unlimited"):
            return service_type, plan_id, code

    return "cdn", target, code


# ── قوانین قبل از پرداخت از موجودی ──────────────────────────────
@router.callback_query(F.data.startswith("pay_balance:"))
async def pay_balance_rules(call: CallbackQuery):
    target = call.data.split(":", 1)[1]
    await safe_edit(call.message, RULES_TEXT,
        reply_markup=await rules_kb(f"pay_balance_confirmed:{target}"), parse_mode="HTML")


@router.callback_query(F.data.startswith("accept_rules:"))
async def accept_rules(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]

    if action.startswith("pay_balance_confirmed:"):
        target = action.split(":", 1)[1]
        service_type, plan_id, code = parse_target(target)
        plan = (TUNNEL_PLANS if service_type == "tunnel" else PLANS).get(plan_id)
        if not plan:
            await call.answer("پلن پیدا نشد!", show_alert=True)
            return

        price = plan["price"]
        if code:
            ok, err_msg, percent = await get_discount_for_user(code, call.from_user.id)
            if not ok:
                await call.answer(err_msg, show_alert=True)
                return
            price = apply_discount(price, percent)

        spent = await db.spend_balance(call.from_user.id, price)
        if not spent:
            await call.answer("موجودی کافی نیست!", show_alert=True)
            return

        await call.answer("⏳ در حال ساخت سرویس...")
        panel_username = generate_tunnel_username() if service_type == "tunnel" else generate_username()
        try:
            panel = marzban_tunnel if service_type == "tunnel" else marzban
            user_data        = await panel.create_user(panel_username, plan["data_limit_gb"], plan["duration_days"])
            subscription_url = user_data.get("subscription_url", "")
            await db.save_service(call.from_user.id, panel_username, plan_id, subscription_url, service_type=service_type)
            if code:
                await db.record_discount_usage(code, call.from_user.id)
            template = await get_text("service_activated_msg")
            text = template.replace("{plan_name}", plan['name']) \
                           .replace("{data_gb}", str(plan['data_limit_gb'])) \
                           .replace("{days}", str(plan['duration_days'])) \
                           .replace("{sub_url}", subscription_url)
            balance = await db.get_balance(call.from_user.id)
            await safe_edit(call.message,
                text + f"\n\n💰 موجودی باقیمانده: <b>{balance:,} تومان</b>",
                reply_markup=await service_info_kb(panel_username), parse_mode="HTML")
        except Exception as e:
            await db.add_balance(call.from_user.id, price)
            await safe_edit(call.message,
                f"❌ خطا در ساخت سرویس: {e}\nموجودیت برگشت داده شد.",
                reply_markup=await back_main_kb())

    elif action.startswith("pay_unlimited_balance_confirmed:"):
        target = action.split(":", 1)[1]
        _, plan_id, code = parse_target(target)
        plan = UNLIMITED_PLANS.get(plan_id)
        if not plan:
            await call.answer("پلن پیدا نشد!", show_alert=True)
            return

        price = plan["price"]
        if code:
            ok, err_msg, percent = await get_discount_for_user(code, call.from_user.id)
            if not ok:
                await call.answer(err_msg, show_alert=True)
                return
            price = apply_discount(price, percent)

        spent = await db.spend_balance(call.from_user.id, price)
        if not spent:
            await call.answer("موجودی کافی نیست!", show_alert=True)
            return

        await call.answer("⏳ در حال ساخت سرویس نامحدود...")
        panel_username = generate_unlimited_username()
        try:
            user_data        = await marzban_unlimited.create_user(panel_username, plan["duration_days"])
            subscription_url = user_data.get("subscription_url", "")
            await db.save_service(call.from_user.id, panel_username, plan_id, subscription_url, service_type="unlimited")
            if code:
                await db.record_discount_usage(code, call.from_user.id)
            template = await get_text("service_activated_msg")
            text = template.replace("{plan_name}", plan['name']) \
                           .replace("{data_gb}", "نامحدود") \
                           .replace("{days}", str(plan['duration_days'])) \
                           .replace("{sub_url}", subscription_url)
            balance = await db.get_balance(call.from_user.id)
            await safe_edit(call.message,
                text + f"\n\n💰 موجودی باقیمانده: <b>{balance:,} تومان</b>",
                reply_markup=await service_info_kb(panel_username), parse_mode="HTML")
        except Exception as e:
            await db.add_balance(call.from_user.id, price)
            await safe_edit(call.message,
                f"❌ خطا در ساخت سرویس نامحدود: {e}\nموجودیت برگشت داده شد.",
                reply_markup=await back_main_kb())

    elif action == "claim_reward":
        pts = await db.get_referral_points(call.from_user.id)
        if pts["points"] < POINTS_PER_REWARD:
            await call.answer("امتیاز کافی نداری!", show_alert=True)
            return
        gigs = pts["points"] // POINTS_PER_REWARD
        await safe_edit(call.message,
            f"🎁 <b>دریافت سرویس رایگان</b>\n\n"
            f"با <b>{gigs * POINTS_PER_REWARD} امتیاز</b> یه سرویس "
            f"<b>{gigs} گیگ / {REWARD_DAYS} روزه</b> برات ساخته میشه.\n"
            f"<b>{pts['points'] % POINTS_PER_REWARD} امتیاز</b> باقی می‌مونه.\n\n"
            f"تأیید می‌کنی؟",
            reply_markup=await confirm_claim_kb(), parse_mode="HTML")

    elif action == "convert_all":
        await do_convert_all_points(call)

    elif action == "renew_balance_confirmed":
        data           = await state.get_data()
        panel_username = data.get("renew_username")
        plan_id        = data.get("renew_plan_id")
        plan           = UNLIMITED_PLANS.get(plan_id)
        if not plan or not panel_username:
            await call.answer("خطا! دوباره از ابتدا امتحان کن.", show_alert=True)
            return
        spent = await db.spend_balance(call.from_user.id, plan["price"])
        if not spent:
            await call.answer("موجودی کافی نیست!", show_alert=True)
            return
        await call.answer("⏳ در حال تمدید...")
        await state.clear()
        try:
            result  = await marzban_unlimited.renew_user(panel_username, plan["duration_days"])
            new_exp = format_expire(result.get("expire", 0))
            balance = await db.get_balance(call.from_user.id)
            await safe_edit(call.message,
                f"✅ <b>اشتراک تمدید شد!</b>\n\n"
                f"🔑 یوزرنیم: <code>{panel_username}</code>\n"
                f"📦 پلن: {plan['name']}\n"
                f"📅 انقضای جدید: <b>{new_exp}</b>\n\n"
                f"💰 موجودی باقیمانده: <b>{balance:,} تومان</b>",
                reply_markup=await main_menu_kb(), parse_mode="HTML")
        except Exception as e:
            await db.add_balance(call.from_user.id, plan["price"])
            await safe_edit(call.message,
                f"❌ خطا در تمدید: {e}\nموجودیت برگشت داده شد.",
                reply_markup=await back_main_kb())


@router.callback_query(F.data.startswith("confirm_pay:"))
async def confirm_payment(call: CallbackQuery, state: FSMContext):
    target = call.data.split(":", 1)[1]
    service_type, plan_id, code = parse_target(target)
    plan = (TUNNEL_PLANS if service_type == "tunnel" else PLANS).get(plan_id)
    if not plan:
        await call.answer("خطا!", show_alert=True)
        return

    price = plan["price"]
    if code:
        ok, err_msg, percent = await get_discount_for_user(code, call.from_user.id)
        if not ok:
            await call.answer(err_msg, show_alert=True)
            return
        price = apply_discount(price, percent)

    template = await get_text("payment_msg")
    text = template.replace("{price}", f"{price:,}") \
                   .replace("{card}", CARD_NUMBER) \
                   .replace("{owner}", CARD_OWNER)
    await state.update_data(plan_id=plan_id, discount_code=code, service_type=service_type)
    await safe_edit(call.message, text, reply_markup=await payment_sent_kb(target), parse_mode="HTML")


@router.callback_query(F.data.startswith("paid:"))
async def payment_done(call: CallbackQuery, state: FSMContext):
    target = call.data.split(":", 1)[1]
    service_type, plan_id, code = parse_target(target)
    await state.update_data(plan_id=plan_id, discount_code=code, service_type=service_type)
    await state.set_state(PurchaseState.waiting_receipt)
    await safe_edit(call.message,
        "📸 <b>ارسال رسید پرداخت</b>\n\n"
        "لطفاً تصویر رسید واریز رو همین الان ارسال کن.\n"
        "بعد از تأیید توسط ادمین، سرویست فعال میشه ✅",
        parse_mode="HTML")


@router.message(PurchaseState.waiting_receipt, F.photo)
async def receive_receipt(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()

    plan_id = data.get("plan_id")
    code = data.get("discount_code")
    service_type = data.get("service_type", "cdn")  # "cdn", "tunnel" یا "unlimited"

    # تشخیص پلن بر اساس نوع سرویس
    if service_type == "tunnel":
        plan = TUNNEL_PLANS.get(plan_id)
        is_unlimited = False
    elif service_type == "unlimited":
        plan = UNLIMITED_PLANS.get(plan_id)
        is_unlimited = True
    else:
        plan = PLANS.get(plan_id)
        is_unlimited = False

    if not plan:
        await message.answer("خطایی رخ داد، دوباره امتحان کن.")
        await state.clear()
        return

    # محاسبه قیمت
    price = plan["price"]
    percent = 0

    if code:
        ok, err_msg, percent = await get_discount_for_user(
            code,
            message.from_user.id
        )

        if ok:
            price = apply_discount(price, percent)
        else:
            code = None

    await state.clear()

    # ساخت یوزرنیم مناسب برای نوع سرویس
    if is_unlimited:
        panel_username = generate_unlimited_username()
    elif service_type == "tunnel":
        panel_username = generate_tunnel_username()
    else:
        panel_username = generate_username()

    # ساخت purchase_id کوتاه برای callback_data ادمین
    import time as _time
    purchase_id = str(int(_time.time()))[-8:]

    # ذخیره درخواست خرید تا زمان تأیید ادمین
    await db.save_pending_purchase(
        purchase_id,
        message.from_user.id,
        plan_id,
        panel_username,
        price,
        code,
        is_unlimited,
        "unlimited" if is_unlimited else service_type
    )

    # ارسال رسید برای ادمین‌ها
    for admin_id in ADMIN_IDS:
        try:
            discount_line = (
                f"\n🏷 کد تخفیف: <code>{code}</code> ({percent}٪)"
                if code else ""
            )

            service_label = (
                "♾️ نامحدود"
                if is_unlimited
                else "⚡️ Tunnel Premium"
                if service_type == "tunnel"
                else "📦 CDN"
            )

            kb = (
                await admin_verify_unlimited_kb(purchase_id)
                if is_unlimited
                else await admin_verify_kb(purchase_id)
            )

            await bot.send_photo(
                chat_id=admin_id,
                photo=message.photo[-1].file_id,
                caption=(
                    f"🔔 <b>درخواست خرید {service_label}</b>\n\n"
                    f"👤 کاربر: "
                    f"<a href='tg://user?id={message.from_user.id}'>"
                    f"{message.from_user.full_name}</a>\n"
                    f"🆔 آیدی: <code>{message.from_user.id}</code>\n"
                    f"📦 پلن: {plan['name']}\n"
                    f"💰 مبلغ: {price:,} تومان{discount_line}\n"
                    f"🔑 یوزرنیم: <code>{panel_username}</code>"
                ),
                reply_markup=kb,
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(
                f"Error sending to admin {admin_id}: {e}",
                exc_info=True
            )

    await message.answer(
        "✅ <b>رسیدت دریافت شد!</b>\n\n"
        "⏳ معمولاً در کمتر از ۳۰ دقیقه سرویست فعال میشه.\n"
        "بعد از تأیید، لینک اتصال برات ارسال میشه 🎉",
        parse_mode="HTML",
        reply_markup=await back_main_kb()
    )
# ══════════════════════════════════════════════════════════════════
#  تأیید / رد ادمین (خرید کارت به کارت)
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("adm_ok:"))
async def admin_approve(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return

    purchase_id = call.data.split(":", 1)[1]
    purchase    = await db.get_pending_purchase(purchase_id)
    if not purchase:
        await call.answer("این درخواست قبلاً پردازش شده!", show_alert=True)
        return

    user_id        = purchase["user_id"]
    plan_id        = purchase["plan_id"]
    panel_username = purchase["panel_username"]
    code           = purchase["code"]
    is_unlimited   = purchase["is_unlimited"]
    service_type   = purchase.get("service_type", "unlimited" if is_unlimited else "cdn")
    plan = UNLIMITED_PLANS.get(plan_id) if is_unlimited else (TUNNEL_PLANS if service_type == "tunnel" else PLANS).get(plan_id)

    await call.answer("⏳ در حال ساخت سرویس...")
    try:
        if is_unlimited:
            user_data = await marzban_unlimited.create_user(panel_username, plan["duration_days"])
        else:
            panel = marzban_tunnel if service_type == "tunnel" else marzban
            user_data = await panel.create_user(panel_username, plan["data_limit_gb"], plan["duration_days"])

        subscription_url = user_data.get("subscription_url", "")
        stype = "unlimited" if is_unlimited else service_type
        await db.save_service(user_id, panel_username, plan_id, subscription_url, service_type=stype)
        if code:
            await db.record_discount_usage(code, user_id)
        await db.delete_pending_purchase(purchase_id)

        template = await get_text("service_activated_msg")
        data_gb  = "نامحدود" if is_unlimited else str(plan.get("data_limit_gb", 0))
        text = template.replace("{plan_name}", plan["name"]) \
                       .replace("{data_gb}", data_gb) \
                       .replace("{days}", str(plan["duration_days"])) \
                       .replace("{sub_url}", subscription_url)

        await safe_send(bot, user_id, text,
            reply_markup=await service_info_kb(panel_username), parse_mode="HTML")
        await safe_edit_caption(call.message,
            call.message.caption + "\n\n✅ <b>تأیید و فعال شد</b>", parse_mode="HTML")
        await call.message.answer(
            f"✅ سرویس برای کاربر <code>{user_id}</code> فعال شد.\n"
            f"🔑 یوزرنیم: <code>{panel_username}</code>",
            parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in admin_approve: {e}")
        await safe_edit_caption(call.message,
            call.message.caption + f"\n\n⚠️ خطا: {e}", parse_mode="HTML")
        await call.message.answer(f"⚠️ خطا: {e}")


@router.callback_query(F.data.startswith("adm_no:"))
async def admin_reject(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return

    purchase_id = call.data.split(":", 1)[1]
    purchase    = await db.get_pending_purchase(purchase_id)
    user_id     = purchase["user_id"] if purchase else None

    if user_id:
        await safe_send(bot, user_id,
            "❌ <b>پرداخت تأیید نشد</b>\n\nمتأسفانه پرداخت شما تأیید نشد.\n"
            "در صورت مشکل با پشتیبانی تماس بگیرید.",
            parse_mode="HTML", reply_markup=await support_kb())
        await db.delete_pending_purchase(purchase_id)

    await safe_edit_caption(call.message,
        call.message.caption + "\n\n❌ <b>رد شد</b>", parse_mode="HTML")
    await call.message.answer(
        f"❌ پرداخت کاربر <code>{user_id}</code> رد شد.", parse_mode="HTML")



# ══════════════════════════════════════════════════════════════════
#  رفرال
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "referral")
async def show_referral(call: CallbackQuery, bot: Bot):
    user_id  = call.from_user.id
    pts_data = await db.get_referral_points(user_id)
    total    = await db.get_referral_count(user_id)
    me       = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{user_id}"
    points   = pts_data["points"]
    gigs     = points // POINTS_PER_REWARD
    remainder = points % POINTS_PER_REWARD

    template = await get_text("referral_msg")
    text = template.replace("{ref_link}", ref_link) \
                   .replace("{points}", str(points)) \
                   .replace("{total_refs}", str(total))

    if gigs > 0:
        text += (
            f"\n\n💡 با <b>{points}</b> امتیاز می‌تونی <b>{gigs} گیگ</b> سرویس رایگان بگیری"
            f" و <b>{remainder}</b> امتیاز باقی بمونه."
        )

    await safe_edit(call.message, text,
        reply_markup=await referral_kb(points >= POINTS_PER_REWARD),
        parse_mode="HTML")


@router.callback_query(F.data == "claim_referral_reward")
async def claim_reward_rules(call: CallbackQuery):
    pts = await db.get_referral_points(call.from_user.id)
    if pts["points"] < POINTS_PER_REWARD:
        await call.answer("امتیاز کافی نداری!", show_alert=True)
        return
    await safe_edit(call.message, RULES_TEXT,
        reply_markup=await rules_kb("claim_reward"), parse_mode="HTML")


@router.callback_query(F.data == "confirm_claim")
async def do_claim_reward(call: CallbackQuery):
    user_id  = call.from_user.id
    pts_data = await db.get_referral_points(user_id)
    points   = pts_data["points"]
    gigs     = points // POINTS_PER_REWARD

    if gigs < 1:
        await call.answer("امتیاز کافی نداری!", show_alert=True)
        return

    total_points_to_spend = gigs * POINTS_PER_REWARD
    spent = await db.spend_referral_points(user_id, total_points_to_spend)
    if not spent:
        await call.answer("خطا در کسر امتیاز!", show_alert=True)
        return

    panel_username = generate_username()
    try:
        user_data        = await marzban.create_user(panel_username, gigs, REWARD_DAYS)
        subscription_url = user_data.get("subscription_url", "")
        await db.save_service(user_id, panel_username, "referral_reward", subscription_url, service_type="free")
        pts_remaining = await db.get_referral_points(user_id)
        await safe_edit(call.message,
            f"🎉 <b>سرویس رایگان فعال شد!</b>\n\n"
            f"💾 حجم: <b>{gigs} گیگابایت</b>\n"
            f"📅 مدت: <b>{REWARD_DAYS} روز</b>\n\n"
            f"🔗 <b>لینک اشتراک:</b>\n<code>{subscription_url}</code>\n\n"
            f"⭐️ امتیاز باقیمانده: <b>{pts_remaining['points']}</b>",
            reply_markup=await service_info_kb(panel_username), parse_mode="HTML")
    except Exception as e:
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as _db:
            await _db.execute("UPDATE referral_points SET points=points+? WHERE user_id=?",
                              (total_points_to_spend, user_id))
            await _db.commit()
        await safe_edit(call.message, f"❌ خطا: {e}\nامتیازت برگشت.", reply_markup=await back_main_kb())


@router.callback_query(F.data == "convert_all_points")
async def convert_all_rules(call: CallbackQuery):
    pts = await db.get_referral_points(call.from_user.id)
    if pts["points"] < POINTS_PER_REWARD:
        await call.answer("امتیاز کافی نداری!", show_alert=True)
        return
    await safe_edit(call.message, RULES_TEXT,
        reply_markup=await rules_kb("convert_all"), parse_mode="HTML")


async def do_convert_all_points(call: CallbackQuery):
    user_id  = call.from_user.id
    pts_data = await db.get_referral_points(user_id)
    points   = pts_data["points"]
    gigs     = points // POINTS_PER_REWARD
    remainder = points % POINTS_PER_REWARD

    if gigs < 1:
        await call.answer("امتیاز کافی نداری!", show_alert=True)
        return

    total_to_spend = gigs * POINTS_PER_REWARD
    spent = await db.spend_referral_points(user_id, total_to_spend)
    if not spent:
        await call.answer("خطا!", show_alert=True)
        return

    panel_username = generate_username()
    try:
        user_data        = await marzban.create_user(panel_username, gigs, REWARD_DAYS)
        subscription_url = user_data.get("subscription_url", "")
        await db.save_service(user_id, panel_username, "referral_reward", subscription_url, service_type="free")
        await safe_edit(call.message,
            f"🎉 <b>تبدیل امتیاز انجام شد!</b>\n\n"
            f"⭐️ امتیاز مصرف‌شده: <b>{total_to_spend}</b>\n"
            f"💾 حجم دریافتی: <b>{gigs} گیگابایت</b>\n"
            f"📅 مدت: <b>{REWARD_DAYS} روز</b>\n"
            f"⭐️ امتیاز باقیمانده: <b>{remainder}</b>\n\n"
            f"🔗 <b>لینک اشتراک:</b>\n<code>{subscription_url}</code>",
            reply_markup=await service_info_kb(panel_username), parse_mode="HTML")
    except Exception as e:
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as _db:
            await _db.execute("UPDATE referral_points SET points=points+? WHERE user_id=?",
                              (total_to_spend, user_id))
            await _db.commit()
        await safe_edit(call.message, f"❌ خطا: {e}\nامتیازت برگشت.", reply_markup=await back_main_kb())


# ══════════════════════════════════════════════════════════════════
#  پشتیبانی / راهنما
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    await safe_edit(call.message, await get_text("support_msg"),
        reply_markup=await support_kb(), parse_mode="HTML")


@router.callback_query(F.data == "guide")
async def guide(call: CallbackQuery):
    await safe_edit(call.message,
        "📖 <b>راهنمای اتصال</b>\n\nسیستم‌عامل خودت رو انتخاب کن:",
        reply_markup=await guide_os_kb(), parse_mode="HTML")


@router.callback_query(F.data == "guide_android")
async def guide_android(call: CallbackQuery):
    await safe_edit(call.message,
        "🤖 <b>راهنمای اندروید</b>\n\n"
        "1️⃣ اپ <b>v2rayNG</b> رو از گوگل پلی نصب کن\n"
        "2️⃣ روی ☰ (منو) → <b>Subscription settings</b> بزن\n"
        "3️⃣ روی + بزن و لینک سابسکریپشنت رو پیست کن و ذخیره کن\n"
        "4️⃣ برگرد به صفحه اصلی → روی ☰ → <b>Update subscription</b> بزن\n"
        "5️⃣ یه سرور رو انتخاب کن و روی ▶️ بزن تا متصل بشی",
        reply_markup=await back_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "guide_ios")
async def guide_ios(call: CallbackQuery):
    await safe_edit(call.message,
        "🍎 <b>راهنمای iOS</b>\n\n"
        "1️⃣ اپ <b>Streisand</b> یا <b>Shadowrocket</b> رو نصب کن\n"
        "2️⃣ روی + → «Subscribe» بزن\n"
        "3️⃣ لینک سابسکریپشنت رو وارد کن\n"
        "4️⃣ روی Connect بزن",
        reply_markup=await back_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "guide_windows")
async def guide_windows(call: CallbackQuery):
    await safe_edit(call.message,
        "🪟 <b>راهنمای ویندوز</b>\n\n"
        "1️⃣ نرم‌افزار <b>v2rayN</b> رو نصب کن\n"
        "2️⃣ از منو Subscription → Subscription settings\n"
        "3️⃣ لینک سابسکریپشنت رو اضافه کن\n"
        "4️⃣ Update subscription → Connect",
        reply_markup=await back_main_kb(), parse_mode="HTML")


@router.callback_query(F.data == "guide_mac")
async def guide_mac(call: CallbackQuery):
    await safe_edit(call.message,
        "🍏 <b>راهنمای مک</b>\n\n"
        "1️⃣ اپ <b>V2Box</b> یا <b>Streisand</b> رو نصب کن\n"
        "2️⃣ Add Config → Add Subscription\n"
        "3️⃣ لینک سابسکریپشنت رو وارد کن\n"
        "4️⃣ سرور مورد نظر رو انتخاب و وصل شو",
        reply_markup=await back_main_kb(), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
#  پنل ادمین
# ══════════════════════════════════════════════════════════════════
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await message.answer("🔧 <b>پنل مدیریت</b>", reply_markup=await admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await safe_edit(call.message, "🔧 <b>پنل مدیریت</b>",
        reply_markup=await admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    bot_count = await db.get_user_count()

    # پنل حجمی
    try:
        users1   = await marzban.get_all_users()
        active1  = sum(1 for u in users1 if u.get("status") == "active")
        expired1 = sum(1 for u in users1 if u.get("status") == "expired")
        limited1 = sum(1 for u in users1 if u.get("status") == "limited")
        panel1_text = (
            f"📦 <b>پنل حجمی</b>\n"
            f"کل: <b>{len(users1)}</b> | "
            f"🟢 {active1} | "
            f"🔴 {expired1} | "
            f"🚫 {limited1}"
        )
    except Exception as e:
        panel1_text = f"📦 <b>پنل حجمی</b>\n❌ خطا: {e}"

    # پنل Tunnel Premium
    try:
        users_t = await marzban_tunnel.get_all_users()
        active_t  = sum(1 for u in users_t if u.get("status") == "active")
        expired_t = sum(1 for u in users_t if u.get("status") == "expired")
        limited_t = sum(1 for u in users_t if u.get("status") == "limited")
        panel_t_text = (
            f"⚡️ <b>پنل Tunnel Premium</b>\n"
            f"کل: <b>{len(users_t)}</b> | "
            f"🟢 {active_t} | "
            f"🔴 {expired_t} | "
            f"🚫 {limited_t}"
        )
    except Exception as e:
        panel_t_text = f"⚡️ <b>پنل Tunnel Premium</b>\n❌ خطا: {e}"

    # پنل نامحدود
    try:
        users2   = await marzban_unlimited.get_all_users()
        active2  = sum(1 for u in users2 if u.get("status") == "active")
        expired2 = sum(1 for u in users2 if u.get("status") == "expired")
        limited2 = sum(1 for u in users2 if u.get("status") == "limited")
        panel2_text = (
            f"♾️ <b>پنل نامحدود</b>\n"
            f"کل: <b>{len(users2)}</b> | "
            f"🟢 {active2} | "
            f"🔴 {expired2} | "
            f"🚫 {limited2}"
        )
    except Exception as e:
        panel2_text = f"♾️ <b>پنل نامحدود</b>\n❌ خطا: {e}"

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from keyboards import btn
    builder = InlineKeyboardBuilder()
    builder.row(btn("admin_search_user", "🔍 جستجوی کاربر برای ویرایش", style="primary", callback_data="admin_search_user"))
    builder.row(btn("back", "🔙 بازگشت", callback_data="admin_panel"))

    text = (
        f"👥 <b>آمار کاربران</b>\n\n"
        f"👤 کاربران ربات: <b>{bot_count}</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{panel1_text}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{panel_t_text}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{panel2_text}"
    )
    await safe_edit(call.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "admin_search_user")
async def admin_search_user(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.edit_user_balance)
    await state.update_data(edit_mode="search")
    await safe_edit(call.message,
        "🔍 <b>جستجوی کاربر</b>\n\nآیدی عددی تلگرام کاربر رو وارد کن:",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML")


@router.message(AdminState.edit_user_balance, F.text)
async def admin_search_user_input(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()

    if data.get("edit_mode") == "search":
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("⚠️ آیدی باید عدد باشه:", reply_markup=await cancel_edit_kb())
            return
        user_id  = int(text)
        balance  = await db.get_balance(user_id)
        pts      = await db.get_referral_points(user_id)
        services = await db.get_user_services(user_id)
        await state.update_data(target_user_id=user_id, edit_mode="idle")
        await state.set_state(None)
        await message.answer(
            f"👤 <b>اطلاعات کاربر {user_id}</b>\n\n"
            f"💰 موجودی: <b>{balance:,} تومان</b>\n"
            f"⭐️ امتیاز رفرال: <b>{pts['points']}</b>\n"
            f"📦 تعداد سرویس: <b>{len(services)}</b>\n\n"
            f"چی رو می‌خوای تغییر بدی؟",
            reply_markup=await admin_edit_user_kb(user_id), parse_mode="HTML"
        )
        return

    if data.get("edit_mode") == "balance":
        target_id = data.get("target_user_id")
        raw = message.text.replace(",", "").replace("،", "").strip()
        if not raw.lstrip("+-").isdigit():
            await message.answer(
                "⚠️ فرمت اشتباهه!\nمثال:\n+50000 (افزایش)\n-30000 (کاهش)\n100000 (مقدار مطلق)",
                reply_markup=await cancel_edit_kb()
            )
            return
        current = await db.get_balance(target_id)
        if raw.startswith("+"):
            new_val = current + int(raw[1:])
            desc = f"افزایش {int(raw[1:]):,} تومان"
        elif raw.startswith("-"):
            new_val = max(0, current - int(raw[1:]))
            desc = f"کاهش {int(raw[1:]):,} تومان"
        else:
            new_val = int(raw)
            desc = f"تنظیم به {new_val:,} تومان"
        await state.set_state(None)
        await message.answer(
            f"💰 <b>تأیید تغییر موجودی</b>\n\n"
            f"کاربر: <code>{target_id}</code>\n"
            f"موجودی فعلی: <b>{current:,} تومان</b>\n"
            f"عملیات: {desc}\n"
            f"موجودی جدید: <b>{new_val:,} تومان</b>",
            reply_markup=await admin_edit_confirm_kb(target_id, f"balance:{raw}"),
            parse_mode="HTML"
        )
        return

    if data.get("edit_mode") == "points":
        target_id = data.get("target_user_id")
        raw = message.text.replace(",", "").replace("،", "").strip()
        if not raw.lstrip("+-").isdigit():
            await message.answer(
                "⚠️ فرمت اشتباهه!\nمثال:\n+5 (افزایش)\n-3 (کاهش)\n10 (مقدار مطلق)",
                reply_markup=await cancel_edit_kb()
            )
            return
        pts = await db.get_referral_points(target_id)
        current = pts["points"]
        if raw.startswith("+"):
            new_val = current + int(raw[1:])
            desc = f"افزایش {raw[1:]} امتیاز"
        elif raw.startswith("-"):
            new_val = max(0, current - int(raw[1:]))
            desc = f"کاهش {raw[1:]} امتیاز"
        else:
            new_val = int(raw)
            desc = f"تنظیم به {new_val} امتیاز"
        await state.set_state(None)
        await message.answer(
            f"⭐️ <b>تأیید تغییر امتیاز</b>\n\n"
            f"کاربر: <code>{target_id}</code>\n"
            f"امتیاز فعلی: <b>{current}</b>\n"
            f"عملیات: {desc}\n"
            f"امتیاز جدید: <b>{new_val}</b>",
            reply_markup=await admin_edit_confirm_kb(target_id, f"points:{raw}"),
            parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("admin_edit_balance:"))
async def admin_edit_balance_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_id = int(call.data.split(":")[1])
    balance = await db.get_balance(user_id)
    await state.set_state(AdminState.edit_user_balance)
    await state.update_data(target_user_id=user_id, edit_mode="balance")
    await safe_edit(call.message,
        f"💰 <b>ویرایش موجودی کاربر {user_id}</b>\n\n"
        f"موجودی فعلی: <b>{balance:,} تومان</b>\n\n"
        f"مقدار رو وارد کن:\n"
        f"• <code>+50000</code> — افزایش\n"
        f"• <code>-30000</code> — کاهش\n"
        f"• <code>100000</code> — تنظیم مستقیم",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_edit_points:"))
async def admin_edit_points_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    user_id = int(call.data.split(":")[1])
    pts     = await db.get_referral_points(user_id)
    await state.set_state(AdminState.edit_user_balance)
    await state.update_data(target_user_id=user_id, edit_mode="points")
    await safe_edit(call.message,
        f"⭐️ <b>ویرایش امتیاز کاربر {user_id}</b>\n\n"
        f"امتیاز فعلی: <b>{pts['points']}</b>\n\n"
        f"مقدار رو وارد کن:\n"
        f"• <code>+5</code> — افزایش\n"
        f"• <code>-3</code> — کاهش\n"
        f"• <code>10</code> — تنظیم مستقیم",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_edit_user:"))
async def admin_edit_user_back(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    user_id  = int(call.data.split(":")[1])
    balance  = await db.get_balance(user_id)
    pts      = await db.get_referral_points(user_id)
    services = await db.get_user_services(user_id)
    await safe_edit(call.message,
        f"👤 <b>اطلاعات کاربر {user_id}</b>\n\n"
        f"💰 موجودی: <b>{balance:,} تومان</b>\n"
        f"⭐️ امتیاز رفرال: <b>{pts['points']}</b>\n"
        f"📦 تعداد سرویس: <b>{len(services)}</b>\n\n"
        f"چی رو می‌خوای تغییر بدی؟",
        reply_markup=await admin_edit_user_kb(user_id), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_edit_confirm:"))
async def admin_edit_confirm(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        return
    parts     = call.data.split(":")
    user_id   = int(parts[1])
    edit_type = parts[2]
    raw       = parts[3]

    if edit_type == "balance":
        current = await db.get_balance(user_id)
        if raw.startswith("+"):
            new_val = current + int(raw[1:])
        elif raw.startswith("-"):
            new_val = max(0, current - int(raw[1:]))
        else:
            new_val = int(raw)
        if new_val > current:
            await db.add_balance(user_id, new_val - current)
        elif new_val < current:
            await db.spend_balance(user_id, current - new_val)
        await safe_edit(call.message,
            f"✅ <b>موجودی آپدیت شد</b>\n\nکاربر: <code>{user_id}</code>\nموجودی جدید: <b>{new_val:,} تومان</b>",
            reply_markup=await admin_edit_user_kb(user_id), parse_mode="HTML")
        await safe_send(bot, user_id,
            f"💰 موجودی کیف پول شما توسط ادمین به <b>{new_val:,} تومان</b> تغییر یافت.",
            parse_mode="HTML")

    elif edit_type == "points":
        pts = await db.get_referral_points(user_id)
        current = pts["points"]
        import aiosqlite
        if raw.startswith("+"):
            new_val = current + int(raw[1:])
            async with aiosqlite.connect(db.DB_PATH) as _db:
                await _db.execute(
                    "INSERT INTO referral_points (user_id, points, total_earned) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET points=points+?, total_earned=total_earned+?",
                    (user_id, int(raw[1:]), int(raw[1:]), int(raw[1:]), int(raw[1:]))
                )
                await _db.commit()
        elif raw.startswith("-"):
            new_val = max(0, current - int(raw[1:]))
            await db.spend_referral_points(user_id, min(current, int(raw[1:])))
        else:
            new_val = int(raw)
            async with aiosqlite.connect(db.DB_PATH) as _db:
                await _db.execute(
                    "INSERT INTO referral_points (user_id, points, total_earned) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET points=?",
                    (user_id, new_val, new_val, new_val)
                )
                await _db.commit()
        await safe_edit(call.message,
            f"✅ <b>امتیاز آپدیت شد</b>\n\nکاربر: <code>{user_id}</code>\nامتیاز جدید: <b>{new_val}</b>",
            reply_markup=await admin_edit_user_kb(user_id), parse_mode="HTML")
        await safe_send(bot, user_id,
            f"⭐️ امتیاز رفرال شما توسط ادمین به <b>{new_val}</b> تغییر یافت.",
            parse_mode="HTML")


@router.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    bot_count = await db.get_user_count()
    now = datetime.now(tz=TEHRAN_TZ).strftime("%H:%M:%S")

    # پنل حجمی
    try:
        stats1 = await marzban.get_system_stats()
        mem_t1 = round(stats1.get("mem_total", 0) / (1024**3), 1)
        mem_u1 = round(stats1.get("mem_used",  0) / (1024**3), 1)
        cpu1   = stats1.get("cpu_usage", 0)
        panel1_text = (
            f"📦 <b>پنل حجمی</b>\n"
            f"🖥 RAM: {mem_u1}GB / {mem_t1}GB\n"
            f"⚙️ CPU: {cpu1:.1f}%"
        )
    except Exception as e:
        panel1_text = f"📦 <b>پنل حجمی</b>\n❌ خطا: {e}"

    # پنل Tunnel Premium
    try:
        stats_t = await marzban_tunnel.get_system_stats()
        mem_tt = round(stats_t.get("mem_total", 0) / (1024**3), 1)
        mem_ut = round(stats_t.get("mem_used", 0) / (1024**3), 1)
        cpu_t = stats_t.get("cpu_usage", 0)
        panel_t_text = (
            f"⚡️ <b>پنل Tunnel Premium</b>\n"
            f"🖥 RAM: {mem_ut}GB / {mem_tt}GB\n"
            f"⚙️ CPU: {cpu_t:.1f}%"
        )
    except Exception as e:
        panel_t_text = f"⚡️ <b>پنل Tunnel Premium</b>\n❌ خطا: {e}"

    # پنل نامحدود
    try:
        stats2 = await marzban_unlimited.get_system_stats()
        mem_t2 = round(stats2.get("mem_total", 0) / (1024**3), 1)
        mem_u2 = round(stats2.get("mem_used",  0) / (1024**3), 1)
        cpu2   = stats2.get("cpu_usage", 0)
        panel2_text = (
            f"♾️ <b>پنل نامحدود</b>\n"
            f"🖥 RAM: {mem_u2}GB / {mem_t2}GB\n"
            f"⚙️ CPU: {cpu2:.1f}%"
        )
    except Exception as e:
        panel2_text = f"♾️ <b>پنل نامحدود</b>\n❌ خطا: {e}"

    text = (
        f"📊 <b>آمار سیستم</b>\n\n"
        f"👥 کاربران ربات: {bot_count}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{panel1_text}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{panel_t_text}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{panel2_text}\n\n"
        f"🕐 {now}"
    )
    await safe_edit(call.message, text, reply_markup=await admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.broadcast_message)
    await safe_edit(call.message, "📢 متن پیام همگانی رو بنویس:", reply_markup=await cancel_edit_kb())


@router.message(AdminState.broadcast_message)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    ids  = await db.get_all_user_ids()
    sent = 0
    for uid in ids:
        try:
            await safe_send(bot, uid, message.text, parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await message.answer(f"✅ پیام به {sent} نفر ارسال شد.", reply_markup=await admin_panel_kb())



# ══════════════════════════════════════════════════════════════════
#  ویرایش متن‌ها (با راهنمای ایموجی پرمیوم)
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "admin_texts")
async def admin_texts_menu(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await safe_edit(call.message,
        "✏️ <b>ویرایش متن‌های ربات</b>\n\n"
        "یکی از متن‌های زیر رو انتخاب کن.\n\n"
        "💡 برای استفاده از ایموجی پرمیوم داخل متن، این فرمت رو بنویس:\n"
        "<code>{{emoji:5368324170671202286:😀}}</code>\n"
        "(عدد، آیدی ایموجی پرمیومه؛ ایموجی بعد از : فقط fallback برای کلاینت‌هایی که ساپورت نمی‌کنن)",
        reply_markup=await admin_texts_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("edit_text:"))
async def edit_text_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    key     = call.data.split(":", 1)[1]
    label   = TEXT_KEYS_FA.get(key, key)
    current = await db.get_text(key) or ""
    await state.set_state(AdminState.editing_text_val)
    await state.update_data(editing_key=key)
    await safe_edit(call.message,
        f"✏️ <b>ویرایش: {label}</b>\n\n"
        f"<b>متن فعلی (خام):</b>\n<blockquote>{current}</blockquote>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"متن جدید رو بنویس و ارسال کن.\n\n"
        f"<b>برای ایموجی پرمیوم:</b>\n"
        f"<code>{{{{emoji:ID:😀}}}}</code>\n\n"
        f"<b>متغیرهای قابل استفاده:</b>\n"
        f"• خوش‌آمد: <code>{{name}}</code>\n"
        f"• پرداخت: <code>{{price}}</code> <code>{{card}}</code> <code>{{owner}}</code>\n"
        f"• فعال‌سازی: <code>{{plan_name}}</code> <code>{{data_gb}}</code> <code>{{days}}</code> <code>{{sub_url}}</code>\n"
        f"• رفرال: <code>{{ref_link}}</code> <code>{{points}}</code> <code>{{total_refs}}</code>",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML")


@router.message(AdminState.editing_text_val)
async def edit_text_save(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    key  = data.get("editing_key")
    await state.clear()
    if not key:
        await message.answer("خطا!", reply_markup=await admin_panel_kb())
        return
    new_text = message.text or message.caption or ""
    if not new_text.strip():
        await message.answer("متن خالیه!", reply_markup=await admin_panel_kb())
        return
    await db.set_text(key, new_text)
    label = TEXT_KEYS_FA.get(key, key)
    preview = render_custom_emojis(new_text)
    await message.answer(
        f"✅ <b>{label}</b> ذخیره شد!\n\n<b>پیش‌نمایش:</b>\n{preview}",
        reply_markup=await admin_texts_kb(), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
#  مدیریت کدهای تخفیف (ادمین)
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "admin_discounts")
async def admin_discounts_menu(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    codes = await db.get_all_discount_codes()
    text = "🏷 <b>مدیریت کدهای تخفیف</b>\n\n"
    if codes:
        text += f"تعداد کل: <b>{len(codes)}</b> کد\n\nروی هر کد بزن تا جزئیاتش رو ببینی:"
    else:
        text += "هنوز هیچ کد تخفیفی ساخته نشده."
    await safe_edit(call.message, text, reply_markup=await admin_discounts_kb(codes), parse_mode="HTML")


@router.callback_query(F.data == "admin_new_discount")
async def admin_new_discount_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminState.new_discount_code)
    await safe_edit(call.message,
        "🏷 <b>ساخت کد تخفیف جدید</b>\n\n"
        "مرحله ۱ از ۴ — کد تخفیف رو وارد کن (انگلیسی، بدون فاصله):\n"
        "<i>مثال: OFF20</i>",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML")


@router.message(AdminState.new_discount_code, F.text)
async def admin_new_discount_code(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    code = message.text.strip().upper()
    if not code.replace("_", "").isalnum():
        await message.answer("⚠️ فقط حروف انگلیسی و عدد و _ مجاز است:", reply_markup=await cancel_edit_kb())
        return
    existing = await db.get_discount_code(code)
    if existing:
        await message.answer("⚠️ این کد از قبل وجود دارد. کد دیگری وارد کن:", reply_markup=await cancel_edit_kb())
        return
    await state.update_data(new_code=code)
    await state.set_state(AdminState.new_discount_percent)
    await message.answer(
        "مرحله ۲ از ۴ — درصد تخفیف رو وارد کن (عدد بین ۱ تا ۱۰۰):\n<i>مثال: 20</i>",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML"
    )


@router.message(AdminState.new_discount_percent, F.text)
async def admin_new_discount_percent(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await message.answer("⚠️ عدد بین ۱ تا ۱۰۰ وارد کن:", reply_markup=await cancel_edit_kb())
        return
    await state.update_data(new_percent=int(text))
    await state.set_state(AdminState.new_discount_limit)
    await message.answer(
        "مرحله ۳ از ۴ — هر کاربر چند بار می‌تونه از این کد استفاده کنه؟\n<i>مثال: 1</i>",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML"
    )


@router.message(AdminState.new_discount_limit, F.text)
async def admin_new_discount_limit(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("⚠️ عدد صحیح مثبت وارد کن:", reply_markup=await cancel_edit_kb())
        return
    await state.update_data(new_limit=int(text))
    await state.set_state(AdminState.new_discount_days)
    await message.answer(
        "مرحله ۴ از ۴ — این کد چند روز اعتبار داشته باشه؟\n"
        "<i>عدد بزن (مثلاً 7) یا برای بدون انقضا بنویس: 0</i>",
        reply_markup=await cancel_edit_kb(), parse_mode="HTML"
    )


@router.message(AdminState.new_discount_days, F.text)
async def admin_new_discount_days(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("⚠️ عدد وارد کن:", reply_markup=await cancel_edit_kb())
        return
    days = int(text)
    data = await state.get_data()
    code    = data.get("new_code")
    percent = data.get("new_percent")
    limit   = data.get("new_limit")
    await state.clear()

    expires_at = None
    if days > 0:
        expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=days)).isoformat()

    await db.create_discount_code(code, percent, limit, expires_at)

    expiry_text = f"{days} روز دیگر" if days > 0 else "بدون انقضا"
    await message.answer(
        f"✅ <b>کد تخفیف ساخته شد!</b>\n\n"
        f"🏷 کد: <code>{code}</code>\n"
        f"📉 درصد: <b>{percent}٪</b>\n"
        f"🔢 سقف استفاده هر کاربر: <b>{limit}</b>\n"
        f"⏰ انقضا: <b>{expiry_text}</b>",
        reply_markup=await admin_panel_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("admin_view_discount:"))
async def admin_view_discount(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    code = call.data.split(":", 1)[1]
    data = await db.get_discount_code(code)
    if not data:
        await call.answer("کد یافت نشد!", show_alert=True)
        return

    total_used = await db.get_code_total_usage_count(code)
    status_text = "🟢 فعال" if data["is_active"] else "🔴 غیرفعال"

    expiry_text = "بدون انقضا"
    if data["expires_at"]:
        try:
            exp_dt = datetime.fromisoformat(data["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            if now > exp_dt:
                expiry_text = f"منقضی شده ({exp_dt.strftime('%Y/%m/%d')})"
            else:
                remaining = exp_dt - now
                expiry_text = f"{remaining.days} روز باقی‌مانده (تا {exp_dt.strftime('%Y/%m/%d')})"
        except Exception:
            expiry_text = data["expires_at"]

    text = (
        f"🏷 <b>جزئیات کد تخفیف</b>\n\n"
        f"کد: <code>{data['code']}</code>\n"
        f"وضعیت: {status_text}\n"
        f"درصد تخفیف: <b>{data['percent']}٪</b>\n"
        f"سقف استفاده هر کاربر: <b>{data['max_per_user']}</b> بار\n"
        f"انقضا: <b>{expiry_text}</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 <b>آمار:</b>\n"
        f"تعداد کل استفاده‌شده: <b>{total_used}</b> بار\n"
        f"تاریخ ساخت: {data['created_at']}"
    )
    await safe_edit(call.message, text,
        reply_markup=await admin_discount_detail_kb(code, bool(data["is_active"])), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_deactivate_discount:"))
async def admin_deactivate_discount(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    code = call.data.split(":", 1)[1]
    await db.deactivate_discount_code(code)
    await call.answer("کد غیرفعال شد")
    await admin_view_discount(call)


@router.callback_query(F.data.startswith("admin_delete_discount:"))
async def admin_delete_discount_confirm(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    code = call.data.split(":", 1)[1]
    await safe_edit(call.message,
        f"⚠️ آیا از حذف کامل کد <code>{code}</code> مطمئنی؟\nاین عمل قابل بازگشت نیست.",
        reply_markup=await admin_confirm_delete_discount_kb(code), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_confirm_delete_discount:"))
async def admin_delete_discount_final(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    code = call.data.split(":", 1)[1]
    await db.delete_discount_code(code)
    await call.answer("کد حذف شد")
    await admin_discounts_menu(call, None)


# ══════════════════════════════════════════════════════════════════
#  مدیریت ایموجی پرمیوم دکمه‌ها (ادمین)
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "admin_buttons")
async def admin_buttons_menu(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await safe_edit(call.message,
        "🔘 <b>ایموجی دکمه‌ها</b>\n\n"
        "روی هر دکمه بزن تا ایموجی پرمیوم اختصاصی‌اش رو تنظیم کنی.\n"
        "🟢 یعنی از قبل ایموجی دارد، ⚪️ یعنی هنوز تنظیم نشده.",
        reply_markup=await admin_buttons_list_kb(0), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_buttons_page:"))
async def admin_buttons_page(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    page = int(call.data.split(":")[1])
    await safe_edit(call.message,
        "🔘 <b>ایموجی دکمه‌ها</b>\n\nروی هر دکمه بزن تا ایموجی پرمیوم اختصاصی‌اش رو تنظیم کنی.",
        reply_markup=await admin_buttons_list_kb(page), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_set_button_emoji:"))
async def admin_set_button_emoji_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_IDS:
        return
    key   = call.data.split(":", 1)[1]
    label = BUTTON_KEYS_FA.get(key, key)
    current = await db.get_button_emoji(key)

    await state.set_state(AdminState.setting_button_emoji)
    await state.update_data(button_key=key)

    current_text = ""
    if current:
        current_text = f"\n\n<b>ایموجی فعلی این دکمه:</b> {current['emoji_id']}"

    await safe_edit(call.message,
        f"🔘 <b>تنظیم ایموجی دکمه:</b>\n{label}{current_text}\n\n"
        f"حالا یکی از این دو کار رو بکن:\n"
        f"1️⃣ خود ایموجی پرمیوم رو مستقیماً اینجا بفرست (تایپ کن و ارسال کن)\n"
        f"2️⃣ یا به این فرمت بنویس: <code>{{{{emoji:ID:😀}}}}</code>",
        reply_markup=await admin_button_emoji_detail_kb(key, bool(current)), parse_mode="HTML")


@router.message(AdminState.setting_button_emoji)
async def admin_set_button_emoji_save(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    key  = data.get("button_key")
    if not key:
        await message.answer("خطا! دوباره از منوی دکمه‌ها شروع کن.", reply_markup=await admin_panel_kb())
        await state.clear()
        return

    # روش ۱: خود ایموجی پرمیوم مستقیم ارسال شده
    emoji_id, fallback = extract_emoji_from_message(message)

    # روش ۲: فرمت متنی {{emoji:ID:fallback}}
    if not emoji_id:
        raw = message.text or message.caption or ""
        emoji_id = extract_emoji_id(raw)
        fallback = "😀"

    if not emoji_id:
        await message.answer(
            "⚠️ ایموجی پرمیوم پیدا نشد. یا خود ایموجی پرمیوم رو بفرست، یا فرمت {{emoji:ID:😀}} رو بنویس.",
            reply_markup=await cancel_edit_kb()
        )
        return

    await db.set_button_emoji(key, emoji_id, fallback or "😀")
    await state.clear()
    label = BUTTON_KEYS_FA.get(key, key)
    await message.answer(
        f"✅ ایموجی دکمه «{label}» ذخیره شد!\n\n"
        f"⚠️ توجه: ایموجی پرمیوم روی دکمه فقط در صورتی نمایش داده میشه که "
        f"اکانتی که ربات را اجرا کرده Telegram Premium داشته باشه.",
        reply_markup=await admin_buttons_list_kb(0)
    )


@router.callback_query(F.data.startswith("admin_remove_button_emoji:"))
async def admin_remove_button_emoji(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return
    key = call.data.split(":", 1)[1]
    await db.remove_button_emoji(key)
    await call.answer("ایموجی این دکمه حذف شد")
    await safe_edit(call.message,
        "🔘 <b>ایموجی دکمه‌ها</b>\n\nروی هر دکمه بزن تا ایموجی پرمیوم اختصاصی‌اش رو تنظیم کنی.",
        reply_markup=await admin_buttons_list_kb(0), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
#  خرید سرویس نامحدود
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data == "buy_unlimited")
async def show_unlimited_plans(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(call.message,
        "♾️ <b>خرید سرویس نامحدود</b>\n\n"
        "سرویس با حجم کاملاً نامحدود:\n\n"
        "✅ بدون محدودیت حجم\n"
        "✅ سرعت بالا\n"
        "✅ پشتیبانی از همه دستگاه‌ها\n\n"
        "پلن مورد نظر رو انتخاب کن:",
        reply_markup=await plans_unlimited_kb(), parse_mode="HTML")


@router.callback_query(F.data.startswith("select_unlimited_plan:"))
async def select_unlimited_plan(call: CallbackQuery, state: FSMContext):
    await state.clear()
    plan_id = call.data.split(":")[1]
    plan    = UNLIMITED_PLANS.get(plan_id)
    if not plan:
        await call.answer("پلن پیدا نشد!", show_alert=True)
        return
    balance         = await db.get_balance(call.from_user.id)
    can_use_balance = balance >= plan["price"]
    text = (
        f"🧾 <b>جزئیات پلن {plan['name']}</b>\n\n"
        f"♾️ حجم: <b>نامحدود</b>\n"
        f"📅 مدت: <b>{plan['duration_days']} روز</b>\n"
        f"💰 قیمت: <b>{plan['price']:,} تومان</b>\n"
        f"👛 موجودی شما: <b>{balance:,} تومان</b>\n\n"
        f"روش پرداخت رو انتخاب کن:"
    )
    await safe_edit(call.message, text,
        reply_markup=await payment_method_unlimited_kb(plan_id, can_use_balance),
        parse_mode="HTML")


# ── کد تخفیف نامحدود ─────────────────────────────────────────────
@router.callback_query(F.data.startswith("enter_unlimited_discount:"))
async def enter_unlimited_discount_start(call: CallbackQuery, state: FSMContext):
    plan_id = call.data.split(":", 1)[1]

    await state.clear()
    await state.update_data(
        discount_plan_id=plan_id,
        service_type="unlimited",
        discount_mode="unlimited"
    )

    await state.set_state(DiscountState.waiting_code)

    await safe_edit(
        call.message,
        "🏷 <b>کد تخفیف</b>\n\nکد تخفیف خودت رو وارد کن:",
        reply_markup=await back_main_kb()
    )


# ── قوانین قبل از پرداخت از موجودی (نامحدود) ───────────────────
@router.callback_query(F.data.startswith("pay_unlimited_balance:"))
async def pay_unlimited_balance_rules(call: CallbackQuery):
    target = call.data.split(":", 1)[1]
    await safe_edit(call.message, RULES_TEXT,
        reply_markup=await rules_kb(f"pay_unlimited_balance_confirmed:{target}"),
        parse_mode="HTML")


# ── تأیید قوانین (نامحدود) در accept_rules ──────────────────────
# این بخش توی accept_rules قبلی به صورت elif اضافه میشه — پایین‌تر handle میشه

@router.callback_query(F.data.startswith("confirm_unlimited_pay:"))
async def confirm_unlimited_payment(call: CallbackQuery, state: FSMContext):
    target = call.data.split(":", 1)[1]
    _, plan_id, code = parse_target(target)
    plan = UNLIMITED_PLANS.get(plan_id)
    if not plan:
        await call.answer("خطا!", show_alert=True)
        return

    price = plan["price"]
    if code:
        ok, err_msg, percent = await get_discount_for_user(code, call.from_user.id)
        if not ok:
            await call.answer(err_msg, show_alert=True)
            return
        price = apply_discount(price, percent)

    template = await get_text("payment_msg")
    text = template.replace("{price}", f"{price:,}") \
                   .replace("{card}", CARD_NUMBER) \
                   .replace("{owner}", CARD_OWNER)
    await state.update_data(plan_id=plan_id, discount_code=code, service_type="unlimited")
    await safe_edit(call.message, text,
        reply_markup=await payment_sent_unlimited_kb(target), parse_mode="HTML")


@router.callback_query(F.data.startswith("paid_unlimited:"))
async def payment_unlimited_done(call: CallbackQuery, state: FSMContext):
    target = call.data.split(":", 1)[1]
    _, plan_id, code = parse_target(target)
    await state.update_data(plan_id=plan_id, discount_code=code, service_type="unlimited")
    await state.set_state(PurchaseState.waiting_receipt)
    await safe_edit(call.message,
        "📸 <b>ارسال رسید پرداخت</b>\n\n"
        "لطفاً تصویر رسید واریز رو همین الان ارسال کن.\n"
        "بعد از تأیید توسط ادمین، سرویست فعال میشه ✅",
        parse_mode="HTML")


# ── تأیید ادمین (نامحدود) ────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════
#  تمدید اشتراک نامحدود
# ══════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("renew_select:"))
async def renew_select(call: CallbackQuery):
    panel_username = call.data.split(":", 1)[1]
    is_unl = panel_username.startswith(UNLIMITED_USER_TAG)

    if not is_unl:
        await call.answer("تمدید فقط برای سرویس‌های نامحدود پشتیبانی میشه.", show_alert=True)
        return

    try:
        ud = await marzban_unlimited.get_user(panel_username)
    except Exception:
        ud = None

    expire_ts  = ud.get("expire", 0) if ud else 0
    status     = ud.get("status", "unknown") if ud else "unknown"
    status_ico = "🟢" if status == "active" else "🔴"

    text = (
        f"🔄 <b>تمدید اشتراک</b>\n\n"
        f"🔑 یوزرنیم: <code>{panel_username}</code>\n"
        f"{status_ico} وضعیت: {'فعال' if status=='active' else 'غیرفعال'}\n"
        f"📅 انقضای فعلی: {format_expire(expire_ts)}\n\n"
        f"پلن تمدید رو انتخاب کن:"
    )
    await safe_edit(call.message, text,
        reply_markup=await renew_unlimited_plans_kb(panel_username),
        parse_mode="HTML")


@router.callback_query(F.data.startswith("renew_plan:"))
async def renew_plan_selected(call: CallbackQuery, state: FSMContext):
    parts          = call.data.split(":", 2)
    panel_username = parts[1]
    plan_id        = parts[2]
    plan           = UNLIMITED_PLANS.get(plan_id)

    if not plan:
        await call.answer("پلن پیدا نشد!", show_alert=True)
        return

    # ذخیره توی state تا callback_data کوتاه بمونه
    await state.update_data(renew_username=panel_username, renew_plan_id=plan_id)

    balance         = await db.get_balance(call.from_user.id)
    can_use_balance = balance >= plan["price"]

    text = (
        f"🔄 <b>تأیید تمدید</b>\n\n"
        f"🔑 اشتراک: <code>{panel_username}</code>\n"
        f"📦 پلن: {plan['name']}\n"
        f"📅 مدت تمدید: {plan['duration_days']} روز\n"
        f"💰 مبلغ: <b>{plan['price']:,} تومان</b>\n"
        f"👛 موجودی شما: <b>{balance:,} تومان</b>\n\n"
        f"روش پرداخت رو انتخاب کن:"
    )
    # callback_data های کوتاه — فقط "rpb" و "rpc" برای balance/card
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from keyboards import btn
    em = await db.get_all_button_emojis()
    builder = InlineKeyboardBuilder()
    if can_use_balance:
        builder.row(btn("renew_pay_balance", "💰 پرداخت از موجودی", em, style="primary",
                        callback_data="renew_do_balance"))
    builder.row(btn("renew_pay_card", "💳 پرداخت کارت به کارت", em, style="primary",
                    callback_data="renew_do_card"))
    builder.row(btn("renew_cancel", "❌ انصراف", em, style="danger",
                    callback_data="check_service"))
    await safe_edit(call.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "renew_do_balance")
async def renew_pay_balance(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    panel_username = data.get("renew_username")
    plan_id        = data.get("renew_plan_id")
    if not panel_username or not plan_id:
        await call.answer("خطا! دوباره از ابتدا امتحان کن.", show_alert=True)
        return
    # ذخیره action توی state و نمایش قوانین
    await state.update_data(renew_rules_action="renew_balance")
    await safe_edit(call.message, RULES_TEXT,
        reply_markup=await rules_kb("renew_balance_confirmed"),
        parse_mode="HTML")


@router.callback_query(F.data == "renew_do_card")
async def renew_pay_card(call: CallbackQuery, state: FSMContext):
    data           = await state.get_data()
    panel_username = data.get("renew_username")
    plan_id        = data.get("renew_plan_id")
    plan           = UNLIMITED_PLANS.get(plan_id)

    if not plan or not panel_username:
        await call.answer("خطا! دوباره از ابتدا امتحان کن.", show_alert=True)
        return

    template = await get_text("payment_msg")
    text = template.replace("{price}", f"{plan['price']:,}") \
                   .replace("{card}", CARD_NUMBER) \
                   .replace("{owner}", CARD_OWNER)

    await state.set_state(RenewState.waiting_receipt)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from keyboards import btn
    em = await db.get_all_button_emojis()
    builder = InlineKeyboardBuilder()
    builder.row(btn("renew_pay_card", "✅ پرداخت کردم، رسید ارسال می‌کنم", em,
                    style="success", callback_data="renew_receipt_confirm"))
    builder.row(btn("renew_cancel", "❌ بازگشت", em, style="danger",
                    callback_data="check_service"))
    await safe_edit(call.message, text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "renew_receipt_confirm")
async def renew_receipt_confirm(call: CallbackQuery, state: FSMContext):
    await state.set_state(RenewState.waiting_receipt)
    await safe_edit(call.message,
        "📸 <b>ارسال رسید تمدید</b>\n\n"
        "تصویر رسید واریز رو همین الان ارسال کن.\n"
        "بعد از تأیید ادمین، اشتراکت تمدید میشه ✅",
        parse_mode="HTML")


@router.message(RenewState.waiting_receipt, F.photo)
async def renew_receipt(message: Message, state: FSMContext, bot: Bot):
    data           = await state.get_data()
    panel_username = data.get("renew_username")
    plan_id        = data.get("renew_plan_id")
    plan           = UNLIMITED_PLANS.get(plan_id)
    await state.clear()

    if not plan or not panel_username:
        await message.answer("خطا! دوباره امتحان کن.", reply_markup=await back_main_kb())
        return

    import time as _time
    purchase_id = "r" + str(int(_time.time()))[-7:]  # prefix r برای تمدید

    # ذخیره اطلاعات تمدید
    await db.save_pending_purchase(
        purchase_id, message.from_user.id, plan_id,
        panel_username, plan["price"], None, True, "unlimited"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=message.photo[-1].file_id,
                caption=(
                    f"🔄 <b>درخواست تمدید اشتراک نامحدود</b>\n\n"
                    f"👤 کاربر: <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a>\n"
                    f"🆔 آیدی: <code>{message.from_user.id}</code>\n"
                    f"🔑 اشتراک: <code>{panel_username}</code>\n"
                    f"📦 پلن تمدید: {plan['name']}\n"
                    f"💰 مبلغ: {plan['price']:,} تومان"
                ),
                reply_markup=await admin_verify_renew_kb(purchase_id),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending renew receipt to admin: {e}")

    await message.answer(
        "✅ <b>رسید تمدید دریافت شد!</b>\n\n"
        "⏳ بعد از تأیید ادمین، اشتراکت تمدید میشه.",
        parse_mode="HTML", reply_markup=await back_main_kb())


@router.callback_query(F.data.startswith("adm_renew_ok:"))
async def admin_renew_approve(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return

    purchase_id = call.data.split(":", 1)[1]
    purchase    = await db.get_pending_purchase(purchase_id)
    if not purchase:
        await call.answer("این درخواست قبلاً پردازش شده!", show_alert=True)
        return

    user_id        = purchase["user_id"]
    panel_username = purchase["panel_username"]
    plan_id        = purchase["plan_id"]
    plan           = UNLIMITED_PLANS.get(plan_id)

    await call.answer("⏳ در حال تمدید...")
    try:
        result   = await marzban_unlimited.renew_user(panel_username, plan["duration_days"])
        new_exp  = format_expire(result.get("expire", 0))
        await db.delete_pending_purchase(purchase_id)

        await safe_send(bot, user_id,
            f"✅ <b>اشتراک تمدید شد!</b>\n\n"
            f"🔑 یوزرنیم: <code>{panel_username}</code>\n"
            f"📦 پلن: {plan['name']}\n"
            f"📅 انقضای جدید: <b>{new_exp}</b>",
            parse_mode="HTML", reply_markup=await main_menu_kb())

        await safe_edit_caption(call.message,
            call.message.caption + "\n\n✅ <b>تمدید شد</b>", parse_mode="HTML")
        await call.message.answer(
            f"✅ اشتراک <code>{panel_username}</code> تمدید شد.\n"
            f"انقضای جدید: {new_exp}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in admin_renew_approve: {e}")
        await safe_edit_caption(call.message,
            call.message.caption + f"\n\n⚠️ خطا: {e}", parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_renew_no:"))
async def admin_renew_reject(call: CallbackQuery, bot: Bot):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return

    purchase_id = call.data.split(":", 1)[1]
    purchase    = await db.get_pending_purchase(purchase_id)
    user_id     = purchase["user_id"] if purchase else None

    if user_id:
        await safe_send(bot, user_id,
            "❌ درخواست تمدید تأیید نشد.\nدر صورت مشکل با پشتیبانی تماس بگیرید.",
            reply_markup=await support_kb())
        await db.delete_pending_purchase(purchase_id)

    await safe_edit_caption(call.message,
        call.message.caption + "\n\n❌ <b>رد شد</b>", parse_mode="HTML")
    await call.message.answer(
        f"❌ تمدید کاربر <code>{user_id}</code> رد شد.", parse_mode="HTML")


