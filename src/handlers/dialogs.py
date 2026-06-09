import asyncio

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import DISTRICTS, THEMES
from db import (
    has_active_subscription,
    has_used_demo,
    is_admin_user,
    mark_demo_used,
    upsert_user,
)
from google_sheets import (
    filter_places,
    format_route,
    get_available_themes,
    get_places,
)
from handlers.middlewares import SubscriptionRequiredMiddleware
from handlers.payments import build_payment_keyboard, show_payment_screen
from handlers.states import Survey

router = Router()
public_router = Router()
protected_router = Router()
fallback_router = Router()
protected_router.message.middleware(SubscriptionRequiredMiddleware())
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
INACTIVE_METRO_PREFIX = "🙅 "


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


def normalize_metro_input(text):
    if text and text.startswith(INACTIVE_METRO_PREFIX):
        return text[len(INACTIVE_METRO_PREFIX):]
    return text


async def build_metros_keyboard(metros):
    from google_sheets import get_places
    places = await get_places()
    metros_display = []
    for metro in metros:
        has_places = any(p.get("Метро") == metro for p in places)
        metros_display.append(metro if has_places else f"{INACTIVE_METRO_PREFIX}{metro}")
    metros_display.append(BACK_TO_START_TEXT)
    return build_keyboard(metros_display, row_width=1)


async def reset_to_start(message: types.Message, state: FSMContext):
    await message.answer("Сессия сбросилась. Давайте начнём заново.")
    await show_district_menu(message, state)


async def load_places_or_notify(message: types.Message):
    return await get_places()


async def show_district_menu(
    message: types.Message,
    state: FSMContext,
    is_demo: bool = False,
    demo_routes_left: int = 0,
):
    await state.clear()
    await state.set_state(Survey.district)
    if is_demo:
        await state.update_data(is_demo=True, demo_routes_left=demo_routes_left)
    await message.answer(
        "Выберите район Петербурга:",
        reply_markup=build_keyboard(list(DISTRICTS.keys()), row_width=1),
    )


@public_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await state.clear()
    await state.set_state(Survey.welcome)
    await message.answer(
        "Привет! 👋\n\nЯ помогу найти интересные места в Петербурге рядом с тобой.",
        reply_markup=build_keyboard([START_BUTTON_TEXT], row_width=1),
    )


@public_router.message(Command("cancel", "restart"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await state.clear()
    await message.answer("Ок, начнем заново.")
    await cmd_start(message, state)


@public_router.message(F.text == START_BUTTON_TEXT)
async def handle_start_button(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
        if is_admin_user(message.from_user.id) or has_active_subscription(message.from_user.id):
            await show_district_menu(message, state)
            return
    await show_payment_screen(message, state)


@public_router.message(Survey.welcome)
async def handle_welcome(message: types.Message, state: FSMContext):
    if message.text == START_BUTTON_TEXT:
        if message.from_user and (
            is_admin_user(message.from_user.id)
            or has_active_subscription(message.from_user.id)
        ):
            await show_district_menu(message, state)
            return
        await show_payment_screen(message, state)
        return

    await message.answer(
        "Нажмите кнопку ниже, чтобы начать.",
        reply_markup=build_keyboard([START_BUTTON_TEXT], row_width=1),
    )


@public_router.callback_query(F.data == "demo_start")
async def handle_demo_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    if not isinstance(callback.message, types.Message):
        return

    telegram_user_id = callback.from_user.id if callback.from_user else None
    if callback.from_user:
        upsert_user(callback.from_user)
    if telegram_user_id and (
        is_admin_user(telegram_user_id) or has_active_subscription(telegram_user_id)
    ):
        await callback.message.answer("Доступ уже открыт. Продолжаем.")
        await show_district_menu(callback.message, state)
        return

    if telegram_user_id and has_used_demo(telegram_user_id) and not is_admin_user(telegram_user_id):
        await callback.message.answer(
            "Вы уже использовали демо-доступ.\n\nВыберите тариф для продолжения:",
            reply_markup=build_payment_keyboard(include_demo=False),
        )
        return
    await show_district_menu(
        callback.message,
        state,
        is_demo=True,
        demo_routes_left=DEMO_ROUTES_LIMIT,
    )


@protected_router.message(Survey.district)
async def handle_district(message: types.Message, state: FSMContext):
    district = message.text
    if district not in DISTRICTS:
        await message.answer("Пожалуйста выберите район из списка 👇")
        return

    await state.update_data(district=district)
    metros = DISTRICTS[district]
    await message.answer(
        f"Район: *{district}*\n\nВыберите ближайшую станцию метро:",
        reply_markup=await build_metros_keyboard(metros),
        parse_mode="Markdown",
    )
    await state.set_state(Survey.metro)


@protected_router.message(Survey.metro)
async def handle_metro(message: types.Message, state: FSMContext):
    data = await state.get_data()
    district = data.get("district")
    metro = normalize_metro_input(message.text)
    if district not in DISTRICTS:
        await reset_to_start(message, state)
        return

    if message.text == BACK_TO_START_TEXT:
        data = await state.get_data()
        is_demo = data.get("is_demo", False)
        demo_routes_left = data.get("demo_routes_left", 0)
        await show_district_menu(message, state, is_demo=is_demo, demo_routes_left=demo_routes_left)
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
            reply_markup=await build_metros_keyboard(DISTRICTS[district]),
        )
        return

    await message.answer(
        f"Станция: *{metro}*\n\nЧто вас интересует?",
        reply_markup=build_keyboard(available, row_width=2),
        parse_mode="Markdown",
    )
    await state.set_state(Survey.theme)


@protected_router.message(Survey.theme)
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

    shown_ids = set(data.get("shown_place_ids", []))
    selected = filter_places(places, metro, theme, exclude_ids=shown_ids)
    if not selected:
        await message.answer("😔 По этой теме пока нет мест у этой станции.")
        return

    new_shown_ids = shown_ids | {p.get("_sheet_row_number") for p in selected}
    await state.update_data(shown_place_ids=list(new_shown_ids))

    route = format_route(selected, metro, theme)
    await message.answer(
        route, reply_markup=types.ReplyKeyboardRemove(), parse_mode="HTML", disable_web_page_preview=True
    )
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


@protected_router.message(Survey.after_route)
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
                reply_markup=await build_metros_keyboard(DISTRICTS[district]),
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
            reply_markup=await build_metros_keyboard(metros),
        )
        await state.set_state(Survey.metro)
        return

    if message.text == BACK_TO_START_TEXT:
        is_demo = data.get("is_demo", False)
        demo_routes_left = data.get("demo_routes_left", 0)
        await show_district_menu(
            message, state, is_demo=is_demo, demo_routes_left=demo_routes_left
        )
        return

    await message.answer(
        "Выберите один из вариантов 👇",
        reply_markup=build_keyboard(AFTER_ROUTE_OPTIONS, row_width=2),
    )


@fallback_router.callback_query()
async def handle_unknown_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Эта кнопка уже неактуальна.")
    if not isinstance(callback.message, types.Message):
        return

    if callback.from_user and (
        is_admin_user(callback.from_user.id)
        or has_active_subscription(callback.from_user.id)
    ):
        await callback.message.answer("Кнопка устарела. Возвращаю к выбору района.")
        await show_district_menu(callback.message, state)
        return

    await callback.message.answer("Кнопка устарела. Откройте новый счет или выберите demo.")
    await show_payment_screen(callback.message, state)


@fallback_router.message()
async def handle_unknown_message(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
        if is_admin_user(message.from_user.id):
            await message.answer(
                "Не понял действие. Для админки используйте /admin, для маршрутов нажмите «Начать».",
                reply_markup=build_keyboard([START_BUTTON_TEXT], row_width=1),
            )
            return

        if has_active_subscription(message.from_user.id):
            await message.answer("Не понял действие. Возвращаю к выбору района.")
            await show_district_menu(message, state)
            return

    await message.answer(
        "Не понял действие. Чтобы продолжить, выберите тариф или demo.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await show_payment_screen(message, state)


router.include_router(public_router)
router.include_router(protected_router)
router.include_router(fallback_router)
