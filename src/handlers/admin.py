import csv
import io
import textwrap

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db import (
    create_admin_subscription,
    delete_active_subscription,
    execute_query,
    get_active_payment,
    get_all_payments,
    get_all_users,
    get_all_users_by_telegram_id,
    get_table_columns,
    get_user_by_telegram_id,
    is_admin_user,
    reset_demo_usage,
)
from handlers.dialogs import (
    ADMIN_MENU_BUTTON_TEXT,
    BACK_TO_START_TEXT,
    HELP_MENU_TEXT,
    ROUTE_MENU_TEXT,
    START_BUTTON_TEXT,
    SUBSCRIPTION_MENU_TEXT,
    build_keyboard,
    show_help,
    show_district_menu,
    show_main_menu,
    show_subscription_status,
)
from handlers.middlewares import AdminOnlyMiddleware
from handlers.states import AdminSubscriptions
from google_sheets import (
    get_places_count,
    reload_places,
    validate_places,
)
from time_utils import format_utc_timestamp_msk

router = Router()

ADMIN_ACCESS_TEXT = "Эта команда доступна только администратору."
ADMIN_MENU_TEXT = "🏳️‍🌈🦄✨  A D M I N K A  ✨🦄🏳️‍🌈"
ADMIN_RELOAD_TEXT = "Обновить данные"
ADMIN_EXPORT_TEXT = "Выгрузить БД в CSV"
ADMIN_SUBSCRIPTIONS_TEXT = "Управление подписками"
ADMIN_BACK_TEXT = "Выйти из админки"
SUBSCRIPTION_ADD_TEXT = "Добавить подписку"
SUBSCRIPTION_DELETE_TEXT = "Удалить подписку"
SUBSCRIPTION_RESET_DEMO_TEXT = "Обнулить demo"
SUBSCRIPTION_USERS_BACK_TEXT = "К списку пользователей"
SUBSCRIPTION_CUSTOM_TEXT = "Custom"
SUBSCRIPTION_BACK_TEXT = "Назад"
SUBSCRIPTION_CONFIRM_DELETE_YES_TEXT = "Да, удалить"
SUBSCRIPTION_CONFIRM_DELETE_NO_TEXT = "Нет"
SUBSCRIPTION_DAY_OPTIONS = {
    "1 день": ("1day", 1),
    "3 дня": ("3days", 3),
    "7 дней": ("7days", 7),
}

router.message.middleware(AdminOnlyMiddleware(ADMIN_ACCESS_TEXT))


def get_admin_keyboard():
    return build_keyboard(
        [ADMIN_RELOAD_TEXT, ADMIN_EXPORT_TEXT, ADMIN_SUBSCRIPTIONS_TEXT, ADMIN_BACK_TEXT],
        row_width=1,
    )


def format_admin_menu_text():
    return "🏳️‍🌈🦄✨  A D M I N K A  ✨🦄🏳️‍🌈"


async def handle_admin_navigation(message: types.Message, state: FSMContext):
    if message.text in {ADMIN_BACK_TEXT, BACK_TO_START_TEXT, START_BUTTON_TEXT}:
        await show_main_menu(message, state)
        return True

    if message.text == ADMIN_MENU_BUTTON_TEXT:
        await state.clear()
        await message.answer(format_admin_menu_text(), reply_markup=get_admin_keyboard())
        return True

    if message.text == ROUTE_MENU_TEXT:
        await show_district_menu(message, state)
        return True

    if message.text == SUBSCRIPTION_MENU_TEXT:
        await show_subscription_status(message, state)
        return True

    if message.text == HELP_MENU_TEXT:
        await show_help(message, state)
        return True

    return False


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


def format_user_label(user):
    username = user["username"] or f"id{user['telegram_user_id']}"
    full_name = " ".join(
        part for part in (user["last_name"], user["first_name"]) if part
    )
    if full_name:
        return f"{username} ({full_name}) · {user['telegram_user_id']}"
    return f"{username} · {user['telegram_user_id']}"


def _format_subscription_status(user, active_payment):
    demo_text = "demo использовано 2/2" if user["demo_used"] else "demo не использовано"
    if not active_payment:
        return f"подписки нет, {demo_text}"

    expires_at = format_utc_timestamp_msk(active_payment["expires_at"])
    source = "админка" if active_payment["created_by_admin"] else "оплата"
    return f"подписка до {expires_at} ({source}), {demo_text}"


def _get_user_admin_label(telegram_user_id):
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        return f"id{telegram_user_id}"
    return format_user_label(user)


async def show_subscription_users(message: types.Message, state: FSMContext):
    users = get_all_users_by_telegram_id()
    if not users:
        await message.answer("Пользователей пока нет.", reply_markup=get_admin_keyboard())
        return

    labels = {format_user_label(user): user["telegram_user_id"] for user in users}
    await state.set_state(AdminSubscriptions.user_list)
    await state.update_data(subscription_user_labels=labels)
    await message.answer(
        "Выберите пользователя:",
        reply_markup=build_keyboard([*labels.keys(), SUBSCRIPTION_BACK_TEXT], row_width=1),
    )


async def show_subscription_user_details(message: types.Message, state: FSMContext, telegram_user_id):
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        await message.answer("Пользователь не найден.")
        await show_subscription_users(message, state)
        return

    active_payment = get_active_payment(telegram_user_id)
    await state.set_state(AdminSubscriptions.user_details)
    await state.update_data(selected_subscription_user_id=telegram_user_id)
    await message.answer(
        f"Выбран: {format_user_label(user)}\n\n{_format_subscription_status(user, active_payment)}",
        reply_markup=build_keyboard(
            [
                SUBSCRIPTION_ADD_TEXT,
                SUBSCRIPTION_DELETE_TEXT,
                SUBSCRIPTION_RESET_DEMO_TEXT,
                SUBSCRIPTION_USERS_BACK_TEXT,
                SUBSCRIPTION_BACK_TEXT,
            ],
            row_width=1,
        ),
    )


async def add_admin_subscription_and_show(message, state, telegram_user_id, plan_code, days):
    create_admin_subscription(
        telegram_user_id=telegram_user_id,
        plan_code=plan_code,
        duration_days=days,
    )
    active_payment = get_active_payment(telegram_user_id)
    expires_at = format_utc_timestamp_msk(active_payment["expires_at"])
    await message.answer(
        f"Пользователь {_get_user_admin_label(telegram_user_id)} подписан на {days} дн.\n"
        f"Подписка до {expires_at}."
    )
    await show_subscription_user_details(message, state, telegram_user_id)


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


@router.message(lambda message: message.text == ADMIN_SUBSCRIPTIONS_TEXT)
async def handle_admin_subscriptions(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    await show_subscription_users(message, state)


@router.message(AdminSubscriptions.user_list)
async def handle_subscription_user_list(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return
    if await handle_admin_navigation(message, state):
        return

    if message.text == SUBSCRIPTION_BACK_TEXT:
        await state.clear()
        await message.answer(format_admin_menu_text(), reply_markup=get_admin_keyboard())
        return

    data = await state.get_data()
    labels = data.get("subscription_user_labels", {})
    telegram_user_id = labels.get(message.text)
    if not telegram_user_id:
        await message.answer("Выберите пользователя из списка.")
        return

    await show_subscription_user_details(message, state, telegram_user_id)


@router.message(AdminSubscriptions.user_details)
async def handle_subscription_user_details(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return
    if await handle_admin_navigation(message, state):
        return

    data = await state.get_data()
    telegram_user_id = data.get("selected_subscription_user_id")
    if not telegram_user_id:
        await show_subscription_users(message, state)
        return

    if message.text == SUBSCRIPTION_ADD_TEXT:
        await state.set_state(AdminSubscriptions.add_subscription)
        await message.answer(
            "На сколько дней добавить подписку?",
            reply_markup=build_keyboard(
                [*SUBSCRIPTION_DAY_OPTIONS.keys(), SUBSCRIPTION_CUSTOM_TEXT, SUBSCRIPTION_BACK_TEXT],
                row_width=1,
            ),
        )
        return

    if message.text == SUBSCRIPTION_DELETE_TEXT:
        user_label = _get_user_admin_label(telegram_user_id)
        if not get_active_payment(telegram_user_id):
            await message.answer(f"У пользователя {user_label} активной подписки нет.")
            await show_subscription_user_details(message, state, telegram_user_id)
            return

        await state.set_state(AdminSubscriptions.confirm_delete)
        await message.answer(
            f"Вы уверены, что хотите безвозвратно удалить текущую подписку для {user_label}?",
            reply_markup=build_keyboard(
                [SUBSCRIPTION_CONFIRM_DELETE_YES_TEXT, SUBSCRIPTION_CONFIRM_DELETE_NO_TEXT],
                row_width=1,
            ),
        )
        return

    if message.text == SUBSCRIPTION_RESET_DEMO_TEXT:
        reset_demo_usage(telegram_user_id)
        await message.answer(f"Demo пользователя {_get_user_admin_label(telegram_user_id)} обнулено.")
        await show_subscription_user_details(message, state, telegram_user_id)
        return

    if message.text == SUBSCRIPTION_USERS_BACK_TEXT:
        await show_subscription_users(message, state)
        return

    if message.text == SUBSCRIPTION_BACK_TEXT:
        await state.clear()
        await message.answer(format_admin_menu_text(), reply_markup=get_admin_keyboard())
        return

    await message.answer("Выберите действие из списка.")


@router.message(AdminSubscriptions.add_subscription)
async def handle_subscription_add(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return
    if await handle_admin_navigation(message, state):
        return

    data = await state.get_data()
    telegram_user_id = data.get("selected_subscription_user_id")
    if not telegram_user_id:
        await show_subscription_users(message, state)
        return

    if message.text == SUBSCRIPTION_BACK_TEXT:
        await show_subscription_user_details(message, state, telegram_user_id)
        return

    if message.text == SUBSCRIPTION_CUSTOM_TEXT:
        await state.set_state(AdminSubscriptions.custom_days)
        await message.answer(
            "На сколько дней? (введите только число)",
            reply_markup=build_keyboard([SUBSCRIPTION_BACK_TEXT], row_width=1),
        )
        return

    option = SUBSCRIPTION_DAY_OPTIONS.get(message.text)
    if not option:
        await message.answer("Выберите срок из списка.")
        return

    plan_code, days = option
    await add_admin_subscription_and_show(message, state, telegram_user_id, plan_code, days)


@router.message(AdminSubscriptions.confirm_delete)
async def handle_subscription_confirm_delete(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return
    if await handle_admin_navigation(message, state):
        return

    data = await state.get_data()
    telegram_user_id = data.get("selected_subscription_user_id")
    if not telegram_user_id:
        await show_subscription_users(message, state)
        return

    user_label = _get_user_admin_label(telegram_user_id)
    if message.text == SUBSCRIPTION_CONFIRM_DELETE_NO_TEXT:
        await message.answer("Удаление отменено.")
        await show_subscription_user_details(message, state, telegram_user_id)
        return

    if message.text != SUBSCRIPTION_CONFIRM_DELETE_YES_TEXT:
        await message.answer(
            "Подтвердите удаление или отмените действие.",
            reply_markup=build_keyboard(
                [SUBSCRIPTION_CONFIRM_DELETE_YES_TEXT, SUBSCRIPTION_CONFIRM_DELETE_NO_TEXT],
                row_width=1,
            ),
        )
        return

    deleted = delete_active_subscription(telegram_user_id)
    if deleted:
        await message.answer(f"Активная подписка пользователя {user_label} удалена.")
    else:
        await message.answer(f"У пользователя {user_label} активной подписки уже нет.")
    await show_subscription_user_details(message, state, telegram_user_id)


@router.message(AdminSubscriptions.custom_days)
async def handle_subscription_custom_days(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return
    if await handle_admin_navigation(message, state):
        return

    data = await state.get_data()
    telegram_user_id = data.get("selected_subscription_user_id")
    if not telegram_user_id:
        await show_subscription_users(message, state)
        return

    if message.text == SUBSCRIPTION_BACK_TEXT:
        await show_subscription_user_details(message, state, telegram_user_id)
        return

    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("Введите положительное число дней.")
        return

    await add_admin_subscription_and_show(
        message,
        state,
        telegram_user_id,
        "custom",
        int(text),
    )


@router.message(lambda message: message.text == ADMIN_BACK_TEXT)
async def handle_admin_back(message: types.Message, state: FSMContext):
    if not message.from_user or not is_admin_user(message.from_user.id):
        await message.answer(ADMIN_ACCESS_TEXT)
        return

    await show_main_menu(message, state)


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
