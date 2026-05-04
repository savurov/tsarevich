import asyncio
import csv
import io

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import DISTRICTS, THEMES
from db import (
    execute_query,
    get_all_subscriptions,
    get_all_users,
    get_table_columns,
    is_admin_user,
    upsert_user,
)
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
ADMIN_ACCESS_TEXT = "Эта команда доступна только администратору."
ADMIN_MENU_TEXT = "Админ-меню"
ADMIN_RELOAD_CALLBACK = "admin:reload_google_data"
ADMIN_EXPORT_CALLBACK = "admin:export_csv"


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


def get_admin_keyboard():
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="Обновить данные из таблицы",
                    callback_data=ADMIN_RELOAD_CALLBACK,
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="Выгрузить БД в CSV",
                    callback_data=ADMIN_EXPORT_CALLBACK,
                )
            ],
        ]
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


def build_csv_file(table_name, columns, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[column] for column in columns])
    return types.BufferedInputFile(
        buffer.getvalue().encode("utf-8"),
        filename=f"{table_name}.csv",
    )


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user:
        upsert_user(message.from_user)
    await show_district_menu(message, state)


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    await message.answer(ADMIN_MENU_TEXT, reply_markup=get_admin_keyboard())


@router.callback_query(F.data == ADMIN_RELOAD_CALLBACK)
async def handle_admin_reload(callback: types.CallbackQuery):
    if not callback.from_user or not is_admin_user(callback.from_user.id):
        await callback.answer(ADMIN_ACCESS_TEXT, show_alert=True)
        return

    try:
        places = await reload_places()
    except PlacesLoadError:
        await callback.answer("Ошибка обновления.", show_alert=True)
        if callback.message:
            await callback.message.answer(PLACES_ERROR_TEXT)
        return

    await callback.answer("Данные обновлены.")
    if callback.message:
        await callback.message.answer(
            f"Данные из Google Sheets обновлены: {len(places)} записей."
        )


@router.callback_query(F.data == ADMIN_EXPORT_CALLBACK)
async def handle_admin_export(callback: types.CallbackQuery):
    if not callback.from_user or not is_admin_user(callback.from_user.id):
        await callback.answer(ADMIN_ACCESS_TEXT, show_alert=True)
        return

    users = get_all_users()
    subscriptions = get_all_subscriptions()
    users_columns = get_table_columns("users")
    subscriptions_columns = get_table_columns("subscriptions")

    if callback.message:
        await callback.message.answer_document(
            build_csv_file("users", users_columns, users)
        )
        await callback.message.answer_document(
            build_csv_file("subscriptions", subscriptions_columns, subscriptions)
        )
    await callback.answer("CSV выгружены.")


@router.message(Command("db"))
async def cmd_db(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer("Эта команда доступна только администратору.")
        return

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
