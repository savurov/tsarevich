import asyncio

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import DISTRICTS, THEMES
from db import execute_query, get_all_users, is_admin_user, upsert_user
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
PLACES_ERROR_TEXT = "Не удалось загрузить места из таблицы. Попробуйте чуть позже."


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


def format_user_row(user):
    return (
        f"id: {user['id']}\n"
        f"telegram_user_id: {user['telegram_user_id']}\n"
        f"username: {user['username'] or '-'}\n"
        f"first_name: {user['first_name'] or '-'}\n"
        f"last_name: {user['last_name'] or '-'}\n"
        f"language_code: {user['language_code'] or '-'}\n"
        f"is_admin: {user['is_admin']}\n"
        f"created_at: {user['created_at']}\n"
        f"updated_at: {user['updated_at']}"
    )


def format_db_result(columns, rows):
    if not rows:
        return "Query OK. 0 rows."

    lines = []
    for row in rows:
        parts = [f"{column}={row[column]}" for column in columns]
        lines.append(", ".join(parts))
    return "\n".join(lines)


async def send_text_in_chunks(message: types.Message, text: str, chunk_size=3500):
    for start in range(0, len(text), chunk_size):
        await message.answer(text[start : start + chunk_size])


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await show_district_menu(message, state)


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    users = get_all_users()
    if not users:
        await message.answer("Пользователей в базе пока нет.")
        return

    chunks = []
    current_chunk = []
    current_length = 0

    for user in users:
        user_text = format_user_row(user)
        block = f"{user_text}\n\n"
        if current_chunk and current_length + len(block) > 3500:
            chunks.append("".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(block)
        current_length += len(block)

    if current_chunk:
        chunks.append("".join(current_chunk))

    for index, chunk in enumerate(chunks, 1):
        header = f"Users {index}/{len(chunks)}\n\n" if len(chunks) > 1 else ""
        await message.answer(f"{header}{chunk}")


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


@router.message(Command("db"))
async def cmd_db(message: types.Message):
    # if not message.from_user or not is_admin_user(message.from_user.id):
    #     await message.answer("Эта команда доступна только администратору.")
    #     return

    text = message.text or ""
    _, _, query = text.partition(" ")
    query = query.strip()
    if not query:
        await message.answer("Использование: /db SELECT * FROM users;")
        return

    try:
        columns, rows = execute_query(query)
    except Exception as exc:
        await message.answer(f"SQL error: {exc}")
        return

    result = format_db_result(columns, rows)
    await send_text_in_chunks(message, result)


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
