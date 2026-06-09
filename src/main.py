import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import TOKEN
from db import run_migrations
from handlers.admin import router as admin_router
from handlers.dialogs import router as dialogs_router
from handlers.payments import router as payments_router
from google_sheets import initialize_places
from logging_utils import configure_logging, log_event, log_exception

configure_logging()
logger = logging.getLogger("teleg.app")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


@dp.errors()
async def handle_error(event):
    log_exception(logger, "Update handling failed", event.exception)

    update = event.update
    message = getattr(update, "message", None)
    callback_query = getattr(update, "callback_query", None)
    if callback_query:
        try:
            await callback_query.answer("Что-то пошло не так.")
        except Exception:
            pass
        message = callback_query.message

    if message:
        try:
            await message.answer(
                "Что-то пошло не так. Я сбросил текущий шаг, нажмите /start и попробуйте заново."
            )
        except Exception:
            pass


async def main():
    log_event(logger, logging.INFO, "Starting bot")
    try:
        run_migrations()
        log_event(logger, logging.INFO, "Migrations applied")
    except Exception as exc:
        log_exception(logger, "Bot startup failed", exc)
        raise

    places, status = await initialize_places()
    if status.has_error:
        log_event(
            logger,
            logging.WARNING,
            "Places loaded with fallback",
            places_count=len(places),
            source=status.source,
            error=status.error_message,
        )
    else:
        log_event(
            logger,
            logging.INFO,
            "Places loaded",
            places_count=len(places),
            source=status.source,
        )

    dp.include_router(admin_router)
    dp.include_router(payments_router)
    dp.include_router(dialogs_router)
    log_event(logger, logging.INFO, "Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
