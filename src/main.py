import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import TOKEN
from db import init_db
from handlers.admin import router as admin_router
from handlers.dialogs import router as dialogs_router
from handlers.payments import router as payments_router
from google_sheets import reload_places
from logging_utils import configure_logging, log_event, log_exception

configure_logging()
logger = logging.getLogger("teleg.app")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


async def main():
    log_event(logger, logging.INFO, "Starting bot")
    try:
        init_db()
        places = await reload_places()
        log_event(logger, logging.INFO, "Places loaded", places_count=len(places))
    except Exception as exc:
        log_exception(logger, "Bot startup failed", exc)
        raise

    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(dialogs_router)
    log_event(logger, logging.INFO, "Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
