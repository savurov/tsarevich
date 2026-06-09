PRAGMA foreign_keys = OFF;

CREATE TABLE payments_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    plan_code TEXT NOT NULL,
    currency TEXT NOT NULL,
    total_amount INTEGER NOT NULL,
    telegram_payment_charge_id TEXT NOT NULL UNIQUE,
    provider_payment_charge_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_by_admin INTEGER NOT NULL DEFAULT 0 CHECK (created_by_admin IN (0, 1)),
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    UNIQUE(telegram_payment_charge_id)
);

INSERT INTO payments_new (
    id,
    telegram_user_id,
    plan_code,
    currency,
    total_amount,
    telegram_payment_charge_id,
    provider_payment_charge_id,
    started_at,
    expires_at,
    created_by_admin,
    raw_payload_json,
    created_at
)
SELECT
    id,
    telegram_user_id,
    plan_code,
    currency,
    total_amount,
    telegram_payment_charge_id,
    provider_payment_charge_id,
    started_at,
    expires_at,
    0,
    raw_payload_json,
    created_at
FROM payments;

DROP TABLE payments;
ALTER TABLE payments_new RENAME TO payments;

CREATE INDEX idx_payments_telegram_user_id
ON payments(telegram_user_id);

CREATE INDEX idx_payments_expires_at
ON payments(expires_at);

CREATE INDEX idx_payments_telegram_user_id_expires_at
ON payments(telegram_user_id, expires_at);

PRAGMA foreign_keys = ON;
