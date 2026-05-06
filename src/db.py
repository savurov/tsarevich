import sqlite3
from contextlib import closing
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
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            external_subscription_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            plan_code TEXT,
            started_at TEXT,
            expires_at TEXT,
            canceled_at TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(provider, external_subscription_id)
        );

        CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id
        ON subscriptions(user_id);

        CREATE INDEX IF NOT EXISTS idx_subscriptions_status
        ON subscriptions(status);
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


def get_all_subscriptions():
    return fetch_all(
        """
        SELECT *
        FROM subscriptions
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


def has_active_subscription(telegram_user_id):
    row = fetch_one(
        """
        SELECT s.id
        FROM subscriptions s
        JOIN users u ON u.id = s.user_id
        WHERE u.telegram_user_id = ?
          AND s.status = 'active'
          AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
        LIMIT 1
        """,
        (telegram_user_id,),
    )
    return row is not None


def create_subscription(
    user_id,
    provider,
    status="pending",
    external_subscription_id=None,
    plan_code=None,
    started_at=None,
    expires_at=None,
    canceled_at=None,
    metadata_json=None,
):
    cursor = execute_write(
        """
        INSERT INTO subscriptions (
            user_id,
            provider,
            external_subscription_id,
            status,
            plan_code,
            started_at,
            expires_at,
            canceled_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            provider,
            external_subscription_id,
            status,
            plan_code,
            started_at,
            expires_at,
            canceled_at,
            metadata_json,
        ),
    )
    return cursor.lastrowid
