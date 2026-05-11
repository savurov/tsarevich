from aiogram.fsm.state import State, StatesGroup


class Survey(StatesGroup):
    welcome = State()
    payment = State()
    district = State()
    metro = State()
    theme = State()
    after_route = State()
