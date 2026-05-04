import asyncio

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import DISTRICTS, THEMES
from db import is_admin_user, upsert_user
from keyboards import AFTER_ROUTE_OPTIONS, build_keyboard
from services.places import (
    PlacesLoadError,
    filter_places,
    format_route,
    get_available_themes,
    get_places,
    reload_places,
)
from states import Survey

router = Router()
PLACES_ERROR_TEXT = (
    "Не удалось загрузить места из таблицы. Попробуйте чуть позже."
)


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
    await show_district_menu(message, state)


@router.message(Command("reload_google_data"))
async def cmd_reload_google_data(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer("Эта команда доступна только администратору.")
        return

    try:
        places = await reload_places()
    except PlacesLoadError:
        await message.answer(PLACES_ERROR_TEXT)
        return

    await message.answer(f"Данные из Google Sheets обновлены: {len(places)} записей.")


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

    if message.text == "📍 Та же станция":
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

    if message.text == "🔀 Сменить станцию":
        metros = DISTRICTS.get(district, [])
        await message.answer(
            "Выберите станцию:",
            reply_markup=build_keyboard(metros, row_width=1),
        )
        await state.set_state(Survey.metro)
        return

    if message.text == "🏠 В начало":
        await show_district_menu(message, state)
        return

    await message.answer(
        "Выберите один из вариантов 👇",
        reply_markup=build_keyboard(AFTER_ROUTE_OPTIONS, row_width=2),
    )
