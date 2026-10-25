import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
import marzban_tunnel
from handlers import router, check_usage_warnings
from webapp import settings as wa_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def warning_scheduler(bot: Bot):
    """هر ۶ ساعت یه بار هشدار مصرف چک میشه"""
    while True:
        await asyncio.sleep(6 * 3600)
        await check_usage_warnings(bot)


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    tasks = [dp.start_polling(bot, skip_updates=True), warning_scheduler(bot)]
    runner, stop = None, None

    if wa_settings.ENABLED:
        # Mini App: روی همان پروسه/دیتابیس. خطای راه‌اندازی Mini App نباید ربات را از کار بیندازد.
        try:
            import asyncio as _a
            from webapp import store as wa_store, service as wa_service, bot_hooks, server as wa_server
            await wa_store.migrate()
            me = await bot.get_me()
            wa_service.notifier = bot_hooks.BotNotifier(bot)
            dp.include_router(bot_hooks.router)          # قبل از router اصلی تا Reply ادمین به تیکت گرفته شود
            await bot_hooks.setup_menu_button(bot)
            runner = await wa_server.start_server(bot, me.username)
            stop = _a.Event()
            tasks.append(wa_service.run_retry_worker(stop))
        except Exception:
            logging.exception("Mini App failed to start; bot continues without it")

    dp.include_router(router)
    print("🤖 ربات VPN راه‌اندازی شد...")
    try:
        await asyncio.gather(*tasks)
    finally:
        if stop:
            stop.set()
        if runner:
            await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
