import csv
import io
import textwrap

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db import (
    execute_query,
    get_all_payments,
    get_all_users,
    get_table_columns,
    is_admin_user,
)
from handlers.dialogs import build_keyboard, show_district_menu
from google_sheets import (
    get_places_count,
    reload_places,
    validate_places,
)

router = Router()

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


def _format_status_source(source):
    if source == "google_sheets":
        return "Google Sheets"
    if source == "disk_cache":
        return "сохраненный кэш на диске"
    if source == "memory_cache":
        return "текущие данные в памяти"
    return "пустой набор данных"


def _truncate_error_details(error_details, limit=500):
    if not error_details:
        return ""
    cleaned = "\n".join(line.strip() for line in error_details.splitlines() if line.strip())
    return textwrap.shorten(cleaned.replace("\n", " | "), width=limit, placeholder="...")


def format_reload_result(old_count, new_count, warnings, status):
    text = (
        f"✨ Обновление таблицы завершено\n📦 Было: {old_count}\n🆕 Стало: {new_count}\n🗃 Источник: {_format_status_source(status.source)}"
    )
    if status.has_error:
        if new_count > 0:
            text += (
                "\n\n⚠️ Google Sheets не обновились. "
                f"Оставили рабочие данные: {new_count} мест."
            )
        else:
            text += "\n\n⚠️ Google Sheets не обновились. Сейчас бот работает с пустыми данными."

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


def format_reload_error(status):
    lines = ["Ой ой ой, ошибка! Данные не загрузились!"]
    if status.source == "memory_cache" and status.places_count > 0:
        lines.append(f"Продолжаю работать на предыдущих данных: {status.places_count} мест.")
    elif status.source == "disk_cache" and status.places_count > 0:
        lines.append(f"Поднял последнюю сохраненную версию: {status.places_count} мест.")
    else:
        lines.append("Старых данных нет, поэтому запросы по местам сейчас будут пустыми.")

    if status.error_message:
        lines.append(f"Причина: {status.error_message}")
    error_details = _truncate_error_details(status.error_details)
    if error_details:
        lines.append(f"Техподробность: {error_details}")
    return "\n\n".join(lines)


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
    places, status = await reload_places()
    if status.has_error:
        await message.answer(
            format_reload_error(status),
            reply_markup=get_admin_keyboard(),
        )
        return

    warnings = validate_places(places)
    await send_text_in_chunks(
        message,
        format_reload_result(old_count, len(places), warnings, status),
    )
    await message.answer("Готово.", reply_markup=get_admin_keyboard())


@router.message(lambda message: message.text == ADMIN_EXPORT_TEXT)
async def handle_admin_export(message: types.Message):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    users = get_all_users()
    payments = get_all_payments()
    users_columns = get_table_columns("users")
    payments_columns = get_table_columns("payments")

    await message.answer_document(build_csv_file("users", users_columns, users))
    await message.answer_document(
        build_csv_file("payments", payments_columns, payments)
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
