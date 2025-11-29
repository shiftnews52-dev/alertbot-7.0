"""main.py - Точка входа приложения с обработкой конфликта"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, executor
from aiogram.utils.exceptions import TerminatedByOtherGetUpdates
from aiogram.contrib.fsm_storage.memory import MemoryStorage  # 👈 ДОБАВИЛИ

from config import BOT_TOKEN
from database import init_db
from handlers import setup_handlers
from tasks import price_collector, signal_analyzer
from pnl_tracker import pnl_tracker
from pnl_tasks import track_signals_pnl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 👇 ДОБАВИЛИ storage=MemoryStorage()
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


async def on_startup(dp: Dispatcher):
    """Запуск бота"""
    logger.info("🤖 Professional Bot starting...")

    # Удаляем вебхук (важно для избежания конфликтов)
    await bot.delete_webhook(drop_pending_updates=True)

    # Инициализация БД
    await init_db()

    # Инициализация PnL трекера
    await pnl_tracker.init_db()
    logger.info("✅ PnL tracker initialized")

    # Регистрация обработчиков
    setup_handlers(dp)

    # Запуск фоновых задач
    loop = asyncio.get_event_loop()
    loop.create_task(price_collector(bot))
    loop.create_task(signal_analyzer(bot))
    loop.create_task(track_signals_pnl(bot))

    logger.info("✅ Professional Bot started successfully!")
    logger.info("🎯 Only 80%+ Confidence signals will be sent!")


async def on_shutdown(dp: Dispatcher):
    """Остановка бота"""
    logger.info("🤖 Bot shutting down...")
    await bot.close()


def handle_polling_error(dispatcher, exception):
    """Обработчик ошибок polling"""
    if isinstance(exception, TerminatedByOtherGetUpdates):
        logger.error("🚨 CONFLICT: Another bot instance is running! Shutting down...")
    else:
        logger.error(f"Polling error: {exception}")


if __name__ == "__main__":
    try:
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            relax=0.1,
            timeout=20,
        )
    except TerminatedByOtherGetUpdates:
        logger.error(
            "🚨 CRITICAL: Bot terminated due to conflict with another instance"
        )
        logger.error("💡 Solution: Stop all other bot instances and restart")
    except Exception as e:
        logger.error(f"🚨 Failed to start bot: {e}")
