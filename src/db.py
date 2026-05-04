import sqlite3
from contextlib import closing
from pathlib import Path

from config import DATABASE_PATH

DB_FILE = Path(DATABASE_PATH)


def get_connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with closing(get_connection()) as connection:
        connection.executescript(
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
        connection.commit()


def upsert_user(telegram_user):
    with closing(get_connection()) as connection:
        connection.execute(
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
        connection.commit()


def get_user_by_telegram_id(telegram_user_id):
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()
    return row


def is_admin_user(telegram_user_id):
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT is_admin
            FROM users
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        ).fetchone()
    return bool(row and row["is_admin"])


def get_all_users():
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM users
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    return rows


def execute_query(query):
    with closing(get_connection()) as connection:
        cursor = connection.execute(query)
        rows = cursor.fetchall() if cursor.description else []
        columns = [description[0] for description in cursor.description or []]
        connection.commit()
    return columns, rows


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
    with closing(get_connection()) as connection:
        cursor = connection.execute(
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
        connection.commit()
    return cursor.lastrowid
