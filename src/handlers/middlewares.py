from aiogram import BaseMiddleware, types

from db import has_active_subscription, is_admin_user
from handlers.payments import show_payment_screen


class SubscriptionRequiredMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, types.Message):
            return await handler(event, data)

        state = data.get("state")
        if not event.from_user or not state:
            await event.answer("Чтобы продолжить, нужен доступ.")
            return None

        state_data = await state.get_data()
        if state_data.get("is_demo"):
            return await handler(event, data)

        user_id = event.from_user.id
        if is_admin_user(user_id) or has_active_subscription(user_id):
            return await handler(event, data)

        await show_payment_screen(event, state)
        return None


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, access_text):
        self.access_text = access_text

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and is_admin_user(user.id):
            return await handler(event, data)

        answer = getattr(event, "answer", None)
        if answer:
            await answer(self.access_text)
        return None
