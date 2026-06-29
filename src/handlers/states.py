from aiogram.fsm.state import State, StatesGroup


class Survey(StatesGroup):
    welcome = State()
    payment = State()
    district = State()
    metro = State()
    theme = State()
    after_route = State()


class AdminSubscriptions(StatesGroup):
    user_search = State()
    user_list = State()
    user_details = State()
    add_subscription = State()
    custom_days = State()
    confirm_delete = State()
