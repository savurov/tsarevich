import asyncio

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import DISTRICTS, DISTRICTS_WITHOUT_METRO, THEMES
from db import (
    get_active_payment,
    has_active_subscription,
    has_used_demo,
    is_admin_user,
    mark_demo_used,
    upsert_user,
)
from google_sheets import (
    ensure_places_loaded,
    filter_places,
    format_route,
    get_available_themes,
)
from handlers.middlewares import SubscriptionRequiredMiddleware
from handlers.payments import build_payment_keyboard, show_payment_screen
from handlers.states import Survey
from time_utils import format_utc_timestamp_msk

router = Router()
public_router = Router()
protected_router = Router()
fallback_router = Router()
protected_router.message.middleware(SubscriptionRequiredMiddleware())
SAME_STATION_TEXT = "📍 Та же станция"
CHANGE_STATION_TEXT = "🔀 Сменить станцию"
BACK_TO_START_TEXT = "🏠 В начало"
START_BUTTON_TEXT = "Начать"
ROUTE_MENU_TEXT = "🗺 Подобрать маршрут"
SUBSCRIPTION_MENU_TEXT = "💳 Подписка"
HELP_MENU_TEXT = "❓ Помощь"
ADMIN_MENU_BUTTON_TEXT = "⚙️ Админка"
MAIN_MENU_BUTTONS = [
    ROUTE_MENU_TEXT,
    SUBSCRIPTION_MENU_TEXT,
    HELP_MENU_TEXT,
]
AFTER_ROUTE_OPTIONS = [
    SAME_STATION_TEXT,
    CHANGE_STATION_TEXT,
    BACK_TO_START_TEXT,
]

DEMO_ROUTES_LIMIT = 2
BACK_TEXT = "← Назад"
INACTIVE_METRO_PREFIX = "🙅 "


def build_keyboard(buttons, row_width=2, nav_buttons=None):
    keyboard = []
    row = []
    for button in buttons:
        row.append(types.KeyboardButton(text=button))
        if len(row) == row_width:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    if nav_buttons:
        keyboard.append([types.KeyboardButton(text=b) for b in nav_buttons])
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def normalize_metro_input(text):
    if text and text.startswith(INACTIVE_METRO_PREFIX):
        return text[len(INACTIVE_METRO_PREFIX) :]
    return text


async def build_metros_keyboard(metros):
    places = await ensure_places_loaded()
    metros_display = []
    for metro in metros:
        has_places = any(p.get("Метро") == metro for p in places)
        metros_display.append(
            metro if has_places else f"{INACTIVE_METRO_PREFIX}{metro}"
        )
    return build_keyboard(metros_display, row_width=1, nav_buttons=[BACK_TEXT, BACK_TO_START_TEXT])


async def reset_to_start(message: types.Message, state: FSMContext):
    await message.answer("Сессия сбросилась.")
    await show_main_menu(message, state)


async def load_places_or_notify(message: types.Message):
    places = await ensure_places_loaded()
    if not places:
        await message.answer("Данные по местам пока не загрузились. Попробуйте ещё раз чуть позже.")
        return None
    return places


def _format_subscription_text(telegram_user_id):
    active_payment = get_active_payment(telegram_user_id)
    if active_payment:
        expires_at = format_utc_timestamp_msk(active_payment["expires_at"])
        return f"Подписка активна до {expires_at}."

    if has_used_demo(telegram_user_id):
        return "Подписки нет. Demo уже использовано."

    return f"Подписки нет. Demo доступно: {DEMO_ROUTES_LIMIT} маршрута."


async def show_main_menu(
    message: types.Message,
    state: FSMContext,
    is_demo: bool = False,
    demo_routes_left: int = 0,
):
    await state.clear()
    if is_demo:
        await state.update_data(is_demo=True, demo_routes_left=demo_routes_left)
    buttons = list(MAIN_MENU_BUTTONS)
    if message.from_user and is_admin_user(message.from_user.id):
        buttons.append(ADMIN_MENU_BUTTON_TEXT)
    await message.answer(
        "Главное меню",
        reply_markup=build_keyboard(buttons, row_width=1),
    )


async def show_subscription_status(message: types.Message, state: FSMContext):
    if not message.from_user:
        await show_payment_screen(message, state)
        return

    text = _format_subscription_text(message.from_user.id)
    if is_admin_user(message.from_user.id) or has_active_subscription(
        message.from_user.id
    ):
        await message.answer(
            f"{text}\n\nМожно строить маршруты.",
            reply_markup=build_keyboard(
                [ROUTE_MENU_TEXT, BACK_TO_START_TEXT], row_width=1
            ),
        )
        return

    await message.answer(text, reply_markup=types.ReplyKeyboardRemove())
    await show_payment_screen(message, state)


async def show_help(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Как это работает:\n\n"
        "1. Выберите район, метро и тему.\n"
        "2. Я пришлю подборку мест с адресами и описаниями.\n"
        f"3. Demo дает {DEMO_ROUTES_LIMIT} маршрута, потом нужен тариф.\n\n"
        "Если Telegram показал ошибку оплаты, значит деньги не списались. "
        "Вернитесь в «Подписка» и откройте новый счет.\n\n"
        "Если что-то пошло не так, напишите мне: @anastasiiatsa",
        reply_markup=build_keyboard(
            [ROUTE_MENU_TEXT, SUBSCRIPTION_MENU_TEXT, BACK_TO_START_TEXT], row_width=1
        ),
    )


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
        reply_markup=build_keyboard(list(DISTRICTS.keys()), row_width=1, nav_buttons=[BACK_TO_START_TEXT]),
    )


@public_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await message.answer(
        "Привет! Я помогу найти интересные места в Петербурге рядом с тобой."
    )
    await show_main_menu(message, state)


@public_router.message(Command("cancel", "restart"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await state.clear()
    await message.answer("Ок, начнем заново.")
    await show_main_menu(message, state)


@public_router.message(F.text.in_({START_BUTTON_TEXT, BACK_TO_START_TEXT}))
async def handle_start_button(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await show_main_menu(message, state)


@public_router.message(F.text == ROUTE_MENU_TEXT)
async def handle_route_menu(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("is_demo"):
        await show_district_menu(
            message,
            state,
            is_demo=True,
            demo_routes_left=data.get("demo_routes_left", 0),
        )
        return

    if message.from_user:
        upsert_user(message.from_user)
        if is_admin_user(message.from_user.id) or has_active_subscription(
            message.from_user.id
        ):
            await show_district_menu(message, state)
            return

        if not has_used_demo(message.from_user.id):
            await show_subscription_status(message, state)
            return

    await show_subscription_status(message, state)


@public_router.message(F.text == SUBSCRIPTION_MENU_TEXT)
async def handle_subscription_menu(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await show_subscription_status(message, state)


@public_router.message(F.text == HELP_MENU_TEXT)
async def handle_help_menu(message: types.Message, state: FSMContext):
    await show_help(message, state)


@public_router.message(F.text == ADMIN_MENU_BUTTON_TEXT)
async def handle_admin_menu_button(message: types.Message):
    from handlers.admin import format_admin_menu_text, get_admin_keyboard

    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer("Эта команда доступна только администратору.")
        return

    await message.answer(format_admin_menu_text(), reply_markup=get_admin_keyboard())


@public_router.message(Survey.welcome)
async def handle_welcome(message: types.Message, state: FSMContext):
    if message.text == START_BUTTON_TEXT:
        await show_main_menu(message, state)
        return

    await message.answer(
        "Выберите действие в главном меню.",
        reply_markup=build_keyboard(MAIN_MENU_BUTTONS, row_width=1),
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

    if (
        telegram_user_id
        and has_used_demo(telegram_user_id)
        and not is_admin_user(telegram_user_id)
    ):
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

    metros = DISTRICTS[district]
    await state.update_data(district=district)

    if district in DISTRICTS_WITHOUT_METRO:
        await state.update_data(metro=district, metros=[district])
        places = await load_places_or_notify(message)
        if places is None:
            return
        available = get_available_themes(places, [district])
        if not available:
            await message.answer("😔 По этому району пока нет мест.")
            return
        await message.answer(
            f"Район: *{district}*\n\nЧто вас интересует?",
            reply_markup=build_keyboard(available, row_width=2),
            parse_mode="Markdown",
        )
        await state.set_state(Survey.theme)
        return

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

    if message.text == BACK_TEXT:
        is_demo = data.get("is_demo", False)
        demo_routes_left = data.get("demo_routes_left", 0)
        await show_district_menu(
            message, state, is_demo=is_demo, demo_routes_left=demo_routes_left
        )
        return

    if metro not in DISTRICTS.get(district, []):
        await message.answer("Пожалуйста выберите станцию из списка 👇")
        return

    await state.update_data(metro=metro, metros=[metro])
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
        reply_markup=build_keyboard(available, row_width=2, nav_buttons=[BACK_TEXT, BACK_TO_START_TEXT]),
        parse_mode="Markdown",
    )
    await state.set_state(Survey.theme)


@protected_router.message(Survey.theme)
async def handle_theme(message: types.Message, state: FSMContext):
    data = await state.get_data()
    district = data.get("district")
    metro = data.get("metro")
    metros = data.get("metros") or ([metro] if metro else [])

    if message.text == BACK_TEXT:
        if not district or district not in DISTRICTS:
            await reset_to_start(message, state)
            return
        await message.answer(
            f"Район: *{district}*\n\nВыберите ближайшую станцию метро:",
            reply_markup=await build_metros_keyboard(DISTRICTS[district]),
            parse_mode="Markdown",
        )
        await state.set_state(Survey.metro)
        return

    theme = message.text
    if theme not in THEMES:
        await message.answer("Пожалуйста выберите тему из списка 👇")
        return

    if not metro:
        await reset_to_start(message, state)
        return

    places = await load_places_or_notify(message)
    if places is None:
        return

    shown_ids = set(data.get("shown_place_ids", []))
    selected = filter_places(places, metros, theme, exclude_ids=shown_ids)
    if not selected:
        await message.answer("😔 По этой теме пока нет мест у этой станции.")
        return

    new_shown_ids = shown_ids | {p.get("_sheet_row_number") for p in selected}
    await state.update_data(shown_place_ids=list(new_shown_ids))

    route = format_route(selected, metro, theme)
    await message.answer(
        route,
        reply_markup=types.ReplyKeyboardRemove(),
        parse_mode="HTML",
        disable_web_page_preview=True,
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
            await show_subscription_status(message, state)
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
    metros = data.get("metros") or ([metro] if metro else [])
    district = data.get("district")
    if not metro or district not in DISTRICTS:
        await reset_to_start(message, state)
        return

    if message.text == SAME_STATION_TEXT:
        places = await load_places_or_notify(message)
        if places is None:
            return

        available = get_available_themes(places, metros)
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
        is_demo = data.get("is_demo", False)
        demo_routes_left = data.get("demo_routes_left", 0)
        if district in DISTRICTS_WITHOUT_METRO:
            await show_district_menu(message, state, is_demo=is_demo, demo_routes_left=demo_routes_left)
            return
        district_metros = DISTRICTS.get(district, [])
        await message.answer(
            "Выберите станцию:",
            reply_markup=await build_metros_keyboard(district_metros),
        )
        await state.set_state(Survey.metro)
        return

    if message.text == BACK_TO_START_TEXT:
        is_demo = data.get("is_demo", False)
        demo_routes_left = data.get("demo_routes_left", 0)
        await show_main_menu(
            message,
            state,
            is_demo=is_demo,
            demo_routes_left=demo_routes_left,
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
        await callback.message.answer("Кнопка устарела. Возвращаю в главное меню.")
        await show_main_menu(callback.message, state)
        return

    await callback.message.answer("Кнопка устарела. Возвращаю в главное меню.")
    await show_main_menu(callback.message, state)


@fallback_router.message()
async def handle_unknown_message(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
        if is_admin_user(message.from_user.id):
            await message.answer("Не понял действие, возвращаю в меню.")
            await show_main_menu(message, state)
            return

        if has_active_subscription(message.from_user.id):
            await message.answer("Не понял действие. Возвращаю в главное меню.")
            await show_main_menu(message, state)
            return

    await message.answer(
        "Не понял действие. Возвращаю в главное меню.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await show_main_menu(message, state)


router.include_router(public_router)
router.include_router(protected_router)
router.include_router(fallback_router)
