import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import TOKEN
from db import init_db
from handlers.admin import router as admin_router
from handlers.dialogs import router as dialogs_router
from google_sheets import reload_places

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


async def main():
    init_db()
    await reload_places()
    dp.include_router(admin_router)
    dp.include_router(dialogs_router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
