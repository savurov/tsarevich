import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import DATABASE_PATH

DB_FILE = Path(DATABASE_PATH)


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def fetch_one(query, params=()):
    with closing(get_connection()) as connection:
        return connection.execute(query, params).fetchone()


def fetch_all(query, params=()):
    with closing(get_connection()) as connection:
        return connection.execute(query, params).fetchall()


def execute_write(query, params=()):
    with closing(get_connection()) as connection, connection:
        cursor = connection.execute(query, params)
    return cursor


def execute_script(script):
    with closing(get_connection()) as connection, connection:
        connection.executescript(script)


def init_db():
    execute_script(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            language_code TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            demo_used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,

            plan_code TEXT NOT NULL,
            currency TEXT NOT NULL,
            total_amount INTEGER NOT NULL,

            telegram_payment_charge_id TEXT NOT NULL UNIQUE,
            provider_payment_charge_id TEXT NOT NULL,

            started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,

            subscription_expiration_date TEXT,
            is_recurring INTEGER,
            is_first_recurring INTEGER,

            raw_payload_json TEXT,

            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(telegram_payment_charge_id)
        );

        CREATE INDEX IF NOT EXISTS idx_payments_user_id
        ON payments(user_id);

        CREATE INDEX IF NOT EXISTS idx_payments_expires_at
        ON payments(expires_at);

        CREATE INDEX IF NOT EXISTS idx_payments_user_expires_at
        ON payments(user_id, expires_at);
        """
    )


def upsert_user(telegram_user):
    execute_write(
        """
        INSERT INTO users (
            telegram_user_id,
            username,
            first_name,
            last_name,
            language_code
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            language_code = excluded.language_code,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            telegram_user.id,
            telegram_user.username,
            telegram_user.first_name,
            telegram_user.last_name,
            telegram_user.language_code,
        ),
    )


def get_user_by_telegram_id(telegram_user_id):
    return fetch_one(
        """
        SELECT *
        FROM users
        WHERE telegram_user_id = ?
        """,
        (telegram_user_id,),
    )


def is_admin_user(telegram_user_id):
    row = fetch_one(
        """
        SELECT is_admin
        FROM users
        WHERE telegram_user_id = ?
        """,
        (telegram_user_id,),
    )
    return bool(row and row["is_admin"])


def get_all_users():
    return fetch_all(
        """
        SELECT *
        FROM users
        ORDER BY created_at DESC, id DESC
        """
    )


def get_all_payments():
    return fetch_all(
        """
        SELECT *
        FROM payments
        ORDER BY created_at DESC, id DESC
        """
    )


def get_table_columns(table_name):
    rows = fetch_all(f"PRAGMA table_info({table_name})")
    return [row["name"] for row in rows]


def execute_query(query):
    with closing(get_connection()) as connection, connection:
        cursor = connection.execute(query)
        rows = cursor.fetchall() if cursor.description else []
        columns = [description[0] for description in cursor.description or []]
    return columns, rows


def create_payment(
    user_id,
    plan_code,
    currency,
    total_amount,
    telegram_payment_charge_id,
    provider_payment_charge_id,
    started_at,
    expires_at,
    subscription_expiration_date=None,
    is_recurring=None,
    is_first_recurring=None,
    raw_payload_json=None,
):
    cursor = execute_write(
        """
        INSERT INTO payments (
            user_id,
            plan_code,
            currency,
            total_amount,
            telegram_payment_charge_id,
            provider_payment_charge_id,
            started_at,
            expires_at,
            subscription_expiration_date,
            is_recurring,
            is_first_recurring,
            raw_payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            plan_code,
            currency,
            total_amount,
            telegram_payment_charge_id,
            provider_payment_charge_id,
            started_at,
            expires_at,
            subscription_expiration_date,
            is_recurring,
            is_first_recurring,
            raw_payload_json,
        ),
    )
    return cursor.lastrowid


def get_payment_by_telegram_charge_id(telegram_payment_charge_id):
    return fetch_one(
        """
        SELECT *
        FROM payments
        WHERE telegram_payment_charge_id = ?
        """,
        (telegram_payment_charge_id,),
    )


def get_active_payment(telegram_user_id):
    return fetch_one(
        """
        SELECT p.*
        FROM payments p
        JOIN users u ON u.id = p.user_id
        WHERE u.telegram_user_id = ?
          AND p.expires_at > CURRENT_TIMESTAMP
        ORDER BY p.expires_at DESC, p.id DESC
        LIMIT 1
        """,
        (telegram_user_id,),
    )


def has_active_subscription(telegram_user_id):
    return get_active_payment(telegram_user_id) is not None


def record_successful_payment(
    telegram_user_id,
    plan_code,
    currency,
    total_amount,
    telegram_payment_charge_id,
    provider_payment_charge_id,
    duration_days,
    subscription_expiration_date=None,
    is_recurring=None,
    is_first_recurring=None,
    raw_payload_json=None,
):
    existing = get_payment_by_telegram_charge_id(telegram_payment_charge_id)
    if existing:
        return existing["id"]

    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        raise ValueError(f"User {telegram_user_id} not found")

    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    active_payment = get_active_payment(telegram_user_id)
    base_time = now
    if active_payment and active_payment["expires_at"]:
        active_expires_at = datetime.strptime(active_payment["expires_at"], "%Y-%m-%d %H:%M:%S")
        if active_expires_at > base_time:
            base_time = active_expires_at

    started_at = base_time.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (base_time + timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")

    return create_payment(
        user_id=user["id"],
        plan_code=plan_code,
        currency=currency,
        total_amount=total_amount,
        telegram_payment_charge_id=telegram_payment_charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        started_at=started_at,
        expires_at=expires_at,
        subscription_expiration_date=subscription_expiration_date,
        is_recurring=int(is_recurring) if is_recurring is not None else None,
        is_first_recurring=int(is_first_recurring) if is_first_recurring is not None else None,
        raw_payload_json=raw_payload_json,
    )


def has_used_demo(telegram_user_id):
    row = fetch_one(
        "SELECT demo_used FROM users WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )
    return bool(row and row["demo_used"])


def mark_demo_used(telegram_user_id):
    execute_write(
        "UPDATE users SET demo_used = 1 WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )
