import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from config import DATABASE_PATH

DB_FILE = Path(DATABASE_PATH)
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


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


def ensure_migrations_table():
    execute_script(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def get_applied_migration_names():
    rows = fetch_all(
        """
        SELECT name
        FROM migrations
        ORDER BY name ASC
        """
    )
    return {row["name"] for row in rows}


def get_migration_files():
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    names = [path.name for path in migration_files]
    if not migration_files:
        raise ValueError(f"No migration files found in {MIGRATIONS_DIR}")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate migration file names found")
    return migration_files


def apply_migration(path):
    sql = path.read_text(encoding="utf-8")
    with closing(get_connection()) as connection, connection:
        connection.executescript(sql)
        connection.execute(
            """
            INSERT INTO migrations (name)
            VALUES (?)
            """,
            (path.name,),
        )


def run_migrations():
    ensure_migrations_table()
    applied_migration_names = get_applied_migration_names()

    for path in get_migration_files():
        if path.name in applied_migration_names:
            continue
        apply_migration(path)


def init_db():
    run_migrations()


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
        ORDER BY created_at DESC, telegram_user_id DESC
        """
    )


def get_all_users_by_telegram_id():
    return fetch_all(
        """
        SELECT *
        FROM users
        ORDER BY telegram_user_id ASC
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
    telegram_user_id,
    plan_code,
    currency,
    total_amount,
    telegram_payment_charge_id,
    provider_payment_charge_id,
    started_at,
    expires_at,
    created_by_admin=0,
    raw_payload_json=None,
):
    cursor = execute_write(
        """
        INSERT INTO payments (
            telegram_user_id,
            plan_code,
            currency,
            total_amount,
            telegram_payment_charge_id,
            provider_payment_charge_id,
            started_at,
            expires_at,
            created_by_admin,
            raw_payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            telegram_user_id,
            plan_code,
            currency,
            total_amount,
            telegram_payment_charge_id,
            provider_payment_charge_id,
            started_at,
            expires_at,
            int(created_by_admin),
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
        WHERE p.telegram_user_id = ?
          AND p.expires_at > CURRENT_TIMESTAMP
        ORDER BY p.expires_at DESC, p.id DESC
        LIMIT 1
        """,
        (telegram_user_id,),
    )


def has_active_subscription(telegram_user_id):
    return get_active_payment(telegram_user_id) is not None


def create_admin_subscription(telegram_user_id, plan_code, duration_days):
    if not get_user_by_telegram_id(telegram_user_id):
        raise ValueError(f"User {telegram_user_id} not found")

    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    started_at = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (now + timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")
    fake_charge_id = f"ADMIN_FAKED_{uuid4()}"

    return create_payment(
        telegram_user_id=telegram_user_id,
        plan_code=plan_code,
        currency="RUB",
        total_amount=0,
        telegram_payment_charge_id=fake_charge_id,
        provider_payment_charge_id=fake_charge_id,
        started_at=started_at,
        expires_at=expires_at,
        created_by_admin=1,
        raw_payload_json="",
    )


def delete_active_subscription(telegram_user_id):
    cursor = execute_write(
        """
        DELETE FROM payments
        WHERE telegram_user_id = ?
          AND expires_at > CURRENT_TIMESTAMP
        """,
        (telegram_user_id,),
    )
    return cursor.rowcount > 0


def record_successful_payment(
    telegram_user_id,
    plan_code,
    currency,
    total_amount,
    telegram_payment_charge_id,
    provider_payment_charge_id,
    duration_days,
    raw_payload_json=None,
):
    existing = get_payment_by_telegram_charge_id(telegram_payment_charge_id)
    if existing:
        return existing["id"]

    if not get_user_by_telegram_id(telegram_user_id):
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
        telegram_user_id=telegram_user_id,
        plan_code=plan_code,
        currency=currency,
        total_amount=total_amount,
        telegram_payment_charge_id=telegram_payment_charge_id,
        provider_payment_charge_id=provider_payment_charge_id,
        started_at=started_at,
        expires_at=expires_at,
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


def reset_demo_usage(telegram_user_id):
    execute_write(
        """
        UPDATE users
        SET demo_used = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_user_id = ?
        """,
        (telegram_user_id,),
    )
