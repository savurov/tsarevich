CREATE TABLE payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
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
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    UNIQUE(telegram_payment_charge_id)
);
