from aiogram.fsm.state import State, StatesGroup


class Survey(StatesGroup):
    district = State()
    metro = State()
    theme = State()
    after_route = State()
