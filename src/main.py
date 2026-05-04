import asyncio

from bot import bot, dp
from db import init_db
from handlers.survey import router
from services.places import reload_places


async def main():
    init_db()
    await reload_places()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
