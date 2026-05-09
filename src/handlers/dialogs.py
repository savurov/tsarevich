import asyncio

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import DISTRICTS, THEMES
from db import has_used_demo, is_admin_user, mark_demo_used, upsert_user
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
START_BUTTON_TEXT = "Начать"
AFTER_ROUTE_OPTIONS = [
    SAME_STATION_TEXT,
    CHANGE_STATION_TEXT,
    BACK_TO_START_TEXT,
]

DEMO_ROUTES_LIMIT = 2

PAYMENT_PLANS_URL = [
    ("290 ₽ — 1 день", "https://yookassa.ru"),
    ("490 ₽ — 3 дня", "https://yookassa.ru"),
    ("690 ₽ — неделя", "https://yookassa.ru"),
]


class Survey(StatesGroup):
    welcome = State()
    payment = State()
    district = State()
    metro = State()
    theme = State()
    after_route = State()


def build_payment_keyboard():
    buttons = [
        [types.InlineKeyboardButton(text="🎁 Демо — бесплатно", callback_data="demo_start")],
    ] + [
        [types.InlineKeyboardButton(text=label, url=url)]
        for label, url in PAYMENT_PLANS_URL
    ]
    buttons.append([types.InlineKeyboardButton(text="Я оплатил ✅", callback_data="check_payment")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


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


async def show_district_menu(message: types.Message, state: FSMContext, is_demo: bool = False, demo_routes_left: int = 0):
    await state.clear()
    await state.set_state(Survey.district)
    if is_demo:
        await state.update_data(is_demo=True, demo_routes_left=demo_routes_left)
    await message.answer(
        "Выберите район Петербурга:",
        reply_markup=build_keyboard(list(DISTRICTS.keys()), row_width=1),
    )


async def show_payment_screen(message: types.Message, state: FSMContext):
    await state.set_state(Survey.payment)
    await message.answer(
        "Выберите тариф для доступа:\n\n"
        "После оплаты нажмите кнопку *«Я оплатил ✅»* внизу.",
        reply_markup=build_payment_keyboard(),
        parse_mode="Markdown",
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await state.set_state(Survey.welcome)
    await message.answer(
        "Привет! 👋\n\nЯ помогу найти интересные места в Петербурге рядом с тобой.",
        reply_markup=build_keyboard([START_BUTTON_TEXT], row_width=1),
    )


@router.message(Survey.welcome)
async def handle_welcome(message: types.Message, state: FSMContext):
    if message.text == START_BUTTON_TEXT:
        await show_payment_screen(message, state)


@router.callback_query(F.data == "demo_start", Survey.payment)
async def handle_demo_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id if callback.from_user else None
    if user_id and has_used_demo(user_id) and not is_admin_user(user_id):
        await callback.message.answer(
            "Вы уже использовали демо-доступ.\n\nВыберите тариф для продолжения:",
            reply_markup=build_payment_keyboard(),
        )
        return
    await show_district_menu(
        callback.message, state,
        is_demo=True, demo_routes_left=DEMO_ROUTES_LIMIT,
    )


@router.callback_query(F.data == "check_payment", Survey.payment)
async def handle_check_payment(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Проверяем оплату... ✅ Готово! Добро пожаловать.")
    await show_district_menu(callback.message, state)


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

    is_demo = data.get("is_demo", False)
    demo_routes_left = data.get("demo_routes_left", 0)

    if is_demo:
        demo_routes_left -= 1
        await state.update_data(demo_routes_left=demo_routes_left)
        if demo_routes_left <= 0:
            if message.from_user:
                mark_demo_used(message.from_user.id)
            await message.answer(
                "🎁 Демо-доступ исчерпан.\n\nЧтобы продолжить, выберите тариф:",
                reply_markup=types.ReplyKeyboardRemove(),
            )
            await show_payment_screen(message, state)
            return

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
        is_demo = data.get("is_demo", False)
        demo_routes_left = data.get("demo_routes_left", 0)
        await show_district_menu(message, state, is_demo=is_demo, demo_routes_left=demo_routes_left)
        return

    await message.answer(
        "Выберите один из вариантов 👇",
        reply_markup=build_keyboard(AFTER_ROUTE_OPTIONS, row_width=2),
    )
