CREATE INDEX idx_payments_telegram_user_id
ON payments(telegram_user_id);

CREATE INDEX idx_payments_expires_at
ON payments(expires_at);

CREATE INDEX idx_payments_telegram_user_id_expires_at
ON payments(telegram_user_id, expires_at);
