import csv
import io

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db import (
    execute_query,
    get_all_subscriptions,
    get_all_users,
    get_table_columns,
    is_admin_user,
)
from handlers.dialogs import build_keyboard, show_district_menu
from google_sheets import (
    PlacesLoadError,
    get_places_count,
    reload_places,
    validate_places,
)

router = Router()

PLACES_ERROR_TEXT = "Не удалось загрузить места из таблицы. Попробуйте чуть позже."
ADMIN_ACCESS_TEXT = "Эта команда доступна только администратору."
ADMIN_MENU_TEXT = "🏳️‍🌈🦄✨  A D M I N K A  ✨🦄🏳️‍🌈"
ADMIN_RELOAD_TEXT = "Обновить данные"
ADMIN_EXPORT_TEXT = "Выгрузить БД в CSV"
ADMIN_BACK_TEXT = "Выйти из админки"


def get_admin_keyboard():
    return build_keyboard(
        [ADMIN_RELOAD_TEXT, ADMIN_EXPORT_TEXT, ADMIN_BACK_TEXT],
        row_width=1,
    )


def format_admin_menu_text():
    return "🏳️‍🌈🦄✨  A D M I N K A  ✨🦄🏳️‍🌈"


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


def format_reload_result(old_count, new_count, warnings):
    text = (
        f"✨ Обновление таблицы завершено\n📦 Было: {old_count}\n🆕 Стало: {new_count}"
    )
    if not warnings:
        return f"{text}\n\n✅ Подозрительных строк не найдено."

    lines = [text, "", "⚠️ Поймались подозрительные строки:"]
    for warning in warnings:
        lines.append(
            f"Строка {warning['row_number']} "
            f"{warning['reason']}\n"
            f"   ↳ {warning['value']}"
        )
    return "\n".join(lines)


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    await message.answer(format_admin_menu_text(), reply_markup=get_admin_keyboard())


@router.message(lambda message: message.text == ADMIN_RELOAD_TEXT)
async def handle_admin_reload(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    old_count = get_places_count()
    try:
        places = await reload_places()
    except PlacesLoadError:
        await message.answer(PLACES_ERROR_TEXT, reply_markup=get_admin_keyboard())
        return

    warnings = validate_places(places)
    await send_text_in_chunks(
        message,
        format_reload_result(old_count, len(places), warnings),
    )
    # await message.answer("Готово.", reply_markup=get_admin_keyboard())


@router.message(lambda message: message.text == ADMIN_EXPORT_TEXT)
async def handle_admin_export(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    users = get_all_users()
    subscriptions = get_all_subscriptions()
    users_columns = get_table_columns("users")
    subscriptions_columns = get_table_columns("subscriptions")

    await message.answer_document(build_csv_file("users", users_columns, users))
    await message.answer_document(
        build_csv_file("subscriptions", subscriptions_columns, subscriptions)
    )
    await message.answer("CSV выгружены.", reply_markup=get_admin_keyboard())


@router.message(lambda message: message.text == ADMIN_BACK_TEXT)
async def handle_admin_back(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    await show_district_menu(message, state)


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
