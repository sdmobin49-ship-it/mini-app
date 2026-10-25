"""
اتصال Mini App به ربات: اعلان‌ها، ارسال رسید به ادمین‌ها و دکمه‌های تأیید/رد/تلاش مجدد،
پاسخ ادمین به تیکت (Reply روی پیام تیکت).
"""
import logging
import re
from typing import Any, Dict, Optional

from aiogram import Router, F, Bot
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, Message, WebAppInfo)

from config import ADMIN_IDS, FORCE_JOIN_CHANNEL
from . import service, settings, store

logger = logging.getLogger(__name__)
router = Router()
TICKET_TAG = re.compile(r"#T(\d+)")


class BotNotifier:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def user(self, user_id: int, text: str) -> None:
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning("notify user %s failed: %s", user_id, type(e).__name__)

    async def admins_alert(self, text: str, order_id: Optional[int] = None) -> None:
        kb = None
        if order_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔁 تلاش مجدد فعال‌سازی", style="primary", callback_data=f"wa_retry:{order_id}")]])
        for admin in ADMIN_IDS:
            try:
                await self.bot.send_message(admin, text, parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                logger.warning("alert admin %s failed: %s", admin, type(e).__name__)

    async def admins_receipt(self, order: Dict[str, Any], image: bytes, caption: str) -> Optional[str]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ تأیید و فعال‌سازی", style="success", callback_data=f"wa_ok:{order['id']}"),
            InlineKeyboardButton(text="❌ رد کردن", style="danger", callback_data=f"wa_no:{order['id']}"),
        ]])
        file_id: Optional[str] = None
        for admin in ADMIN_IDS:
            try:
                photo = file_id or BufferedInputFile(image, filename="receipt.jpg")
                msg = await self.bot.send_photo(admin, photo, caption=caption, parse_mode="HTML", reply_markup=kb)
                file_id = file_id or msg.photo[-1].file_id
            except Exception as e:
                logger.warning("send receipt to admin %s failed: %s", admin, type(e).__name__)
        return file_id

    async def admins_ticket(self, ticket: Dict[str, Any], body: str) -> None:
        text = (f"🎫 <b>تیکت پشتیبانی</b> #T{ticket['id']}\n"
                f"👤 کاربر: <code>{ticket['user_id']}</code>\n"
                f"🗂 دسته: {service.TICKET_CATEGORIES.get(ticket['category'], ticket['category'])}\n"
                f"📝 موضوع: {_esc(ticket['subject'])}\n\n{_esc(body)}\n\n"
                f"↩️ برای پاسخ، روی همین پیام Reply بزن.")
        for admin in ADMIN_IDS:
            try:
                await self.bot.send_message(admin, text, parse_mode="HTML")
            except Exception as e:
                logger.warning("ticket to admin %s failed: %s", admin, type(e).__name__)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def check_membership(bot: Bot, user_id: int) -> bool:
    """همان منطق ربات (handlers.check_membership): عضویت اجباری کانال."""
    if not FORCE_JOIN_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return True


async def setup_menu_button(bot: Bot) -> None:
    if not settings.WEBAPP_URL:
        return
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="Spider VPN", web_app=WebAppInfo(url=settings.WEBAPP_URL + "/")))
    except Exception as e:
        logger.warning("set_chat_menu_button failed: %s", type(e).__name__)


async def _finish(call: CallbackQuery, suffix: str) -> None:
    try:
        if call.message.caption is not None:
            await call.message.edit_caption(caption=call.message.caption + suffix, parse_mode="HTML")
        else:
            await call.message.edit_text((call.message.text or "") + suffix, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("wa_ok:"))
async def wa_ok(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return
    res = await service.approve_order(int(call.data.split(":", 1)[1]), call.from_user.id)
    if res == "already_processed":
        await call.answer("این سفارش قبلاً پردازش شده!", show_alert=True)
        return
    await call.answer("✅ تأیید شد؛ فعال‌سازی در حال انجام است.")
    await _finish(call, "\n\n✅ <b>تأیید شد</b>")


@router.callback_query(F.data.startswith("wa_no:"))
async def wa_no(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return
    res = await service.reject_order(int(call.data.split(":", 1)[1]), call.from_user.id)
    if res == "already_processed":
        await call.answer("این سفارش قبلاً پردازش شده!", show_alert=True)
        return
    await call.answer("رد شد.")
    await _finish(call, "\n\n❌ <b>رد شد</b>")


@router.callback_query(F.data.startswith("wa_retry:"))
async def wa_retry(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("دسترسی ندارید!", show_alert=True)
        return
    oid = int(call.data.split(":", 1)[1])
    if not await store.reset_for_retry(oid):
        await call.answer("این سفارش دیگر در وضعیت ناموفق نیست.", show_alert=True)
        return
    await call.answer("🔁 تلاش مجدد شروع شد.")
    await service.provision(oid)


@router.message(F.text, F.from_user.id.in_(set(ADMIN_IDS)), F.reply_to_message.text.regexp(r"#T\d+"))
async def admin_ticket_reply(message: Message, bot: Bot):
    m = TICKET_TAG.search(message.reply_to_message.text or "")
    if not m:
        return
    tid = int(m.group(1))
    user_id = await service.admin_reply_ticket(tid, message.text.strip()[:2000])
    if user_id is None:
        await message.reply("تیکت پیدا نشد.")
        return
    await BotNotifier(bot).user(user_id, f"💬 پاسخ پشتیبانی به تیکت #{tid}:\n\n{_esc(message.text.strip())}")
    await message.reply("✅ پاسخ برای کاربر ارسال شد.")
