import asyncio

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import DISTRICTS, PLANS, THEMES
from db import has_active_subscription, upsert_user
from google_sheets import (
    PlacesLoadError,
    filter_places,
    format_route,
    get_available_themes,
    get_places,
)

router = Router()
PLACES_ERROR_TEXT = "Не удалось загрузить места из таблицы. Попробуйте чуть позже."
SAME_STATION_TEXT = "📍 Та же станция"
CHANGE_STATION_TEXT = "🔀 Сменить станцию"
BACK_TO_START_TEXT = "🏠 В начало"
AFTER_ROUTE_OPTIONS = [
    SAME_STATION_TEXT,
    CHANGE_STATION_TEXT,
    BACK_TO_START_TEXT,
]


class Survey(StatesGroup):
    payment = State()
    district = State()
    metro = State()
    theme = State()
    after_route = State()


def build_payment_keyboard():
    buttons = [
        types.InlineKeyboardButton(
            text=f"📍 {PLANS['district']['label']} — {PLANS['district']['price']} ₽",
            callback_data="buy:district",
        ),
        types.InlineKeyboardButton(
            text=f"🌍 {PLANS['full']['label']} — {PLANS['full']['price']} ₽",
            callback_data="buy:full",
        ),
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=[[b] for b in buttons])


async def show_payment_menu(message: types.Message, state: FSMContext):
    await state.set_state(Survey.payment)
    await message.answer(
        "👋 Привет!\n\n"
        "Чтобы пользоваться ботом, выберите тариф:\n\n"
        f"📍 *{PLANS['district']['label']}* — доступ к маршрутам одного района на месяц\n"
        f"*{PLANS['district']['price']} ₽*\n\n"
        f"🌍 *{PLANS['full']['label']}* — все районы без ограничений на месяц\n"
        f"*{PLANS['full']['price']} ₽*",
        reply_markup=build_payment_keyboard(),
        parse_mode="Markdown",
    )


def build_keyboard(buttons, row_width=2):
    keyboard = []
    row = []
    for button in buttons:
        row.append(types.KeyboardButton(text=button))
        if len(row) == row_width:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


async def reset_to_start(message: types.Message, state: FSMContext):
    await message.answer("Сессия сбросилась. Давайте начнём заново.")
    await show_district_menu(message, state)


async def load_places_or_notify(message: types.Message):
    try:
        return await get_places()
    except PlacesLoadError:
        await message.answer(PLACES_ERROR_TEXT)
        return None


async def show_district_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Survey.district)
    await message.answer(
        "Привет! 👋 Выберите район Петербурга:",
        reply_markup=build_keyboard(list(DISTRICTS.keys()), row_width=1),
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
        if not has_active_subscription(message.from_user.id):
            await show_payment_menu(message, state)
            return
    await show_district_menu(message, state)


@router.callback_query(Survey.payment, F.data.startswith("buy:"))
async def handle_plan_selection(callback: types.CallbackQuery, state: FSMContext):
    plan_key = callback.data.split(":")[1]
    plan = PLANS.get(plan_key)
    if not plan or not callback.message:
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Вы выбрали: *{plan['label']}* — {plan['price']} ₽\n\n"
        "⏳ Переходим к оплате...",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(Survey.district)
async def handle_district(message: types.Message, state: FSMContext):
    district = message.text
    if district not in DISTRICTS:
        await message.answer("Пожалуйста выберите район из списка 👇")
        return

    await state.update_data(district=district)
    metros = DISTRICTS[district]
    await message.answer(
        f"Район: *{district}*\n\nВыберите ближайшую станцию метро:",
        reply_markup=build_keyboard(metros, row_width=1),
        parse_mode="Markdown",
    )
    await state.set_state(Survey.metro)


@router.message(Survey.metro)
async def handle_metro(message: types.Message, state: FSMContext):
    data = await state.get_data()
    district = data.get("district")
    metro = message.text
    if district not in DISTRICTS:
        await reset_to_start(message, state)
        return

    if metro not in DISTRICTS.get(district, []):
        await message.answer("Пожалуйста выберите станцию из списка 👇")
        return

    await state.update_data(metro=metro)
    places = await load_places_or_notify(message)
    if places is None:
        return

    available = get_available_themes(places, metro)
    if not available:
        await message.answer(
            "😔 По этой станции пока нет мест. Попробуйте другую.",
            reply_markup=build_keyboard(DISTRICTS[district], row_width=1),
        )
        return

    await message.answer(
        f"Станция: *{metro}*\n\nЧто вас интересует?",
        reply_markup=build_keyboard(available, row_width=2),
        parse_mode="Markdown",
    )
    await state.set_state(Survey.theme)


@router.message(Survey.theme)
async def handle_theme(message: types.Message, state: FSMContext):
    theme = message.text
    if theme not in THEMES:
        await message.answer("Пожалуйста выберите тему из списка 👇")
        return

    data = await state.get_data()
    metro = data.get("metro")
    if not metro:
        await reset_to_start(message, state)
        return

    places = await load_places_or_notify(message)
    if places is None:
        return

    selected = filter_places(places, metro, theme)
    if not selected:
        await message.answer("😔 По этой теме пока нет мест у этой станции.")
        return

    route = format_route(selected, metro, theme)
    await message.answer(route, reply_markup=types.ReplyKeyboardRemove())
    await asyncio.sleep(0.3)
    await message.answer(
        "Хотите посмотреть ещё?",
        reply_markup=build_keyboard(AFTER_ROUTE_OPTIONS, row_width=2),
    )
    await state.set_state(Survey.after_route)


@router.message(Survey.after_route)
async def handle_after_route(message: types.Message, state: FSMContext):
    data = await state.get_data()
    metro = data.get("metro")
    district = data.get("district")
    if not metro or district not in DISTRICTS:
        await reset_to_start(message, state)
        return

    if message.text == SAME_STATION_TEXT:
        places = await load_places_or_notify(message)
        if places is None:
            return

        available = get_available_themes(places, metro)
        if not available:
            await message.answer(
                "😔 По этой станции пока нет мест. Попробуйте другую.",
                reply_markup=build_keyboard(DISTRICTS[district], row_width=1),
            )
            await state.set_state(Survey.metro)
            return

        await message.answer(
            "Выберите тему:",
            reply_markup=build_keyboard(available, row_width=2),
        )
        await state.set_state(Survey.theme)
        return

    if message.text == CHANGE_STATION_TEXT:
        metros = DISTRICTS.get(district, [])
        await message.answer(
            "Выберите станцию:",
            reply_markup=build_keyboard(metros, row_width=1),
        )
        await state.set_state(Survey.metro)
        return

    if message.text == BACK_TO_START_TEXT:
        await show_district_menu(message, state)
        return

    await message.answer(
        "Выберите один из вариантов 👇",
        reply_markup=build_keyboard(AFTER_ROUTE_OPTIONS, row_width=2),
    )
