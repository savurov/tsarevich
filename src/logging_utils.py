import logging


def configure_logging(level=logging.INFO):
    logging.basicConfig(level=level, format="%(message)s")


def _format_log_line(message, telegram_user_id=None, **fields):
    parts = [message]
    if telegram_user_id is not None:
        parts.append(f"telegram_user_id={telegram_user_id}")

    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")

    return " | ".join(parts)


def log_event(logger, level, message, telegram_user_id=None, **fields):
    logger.log(level, _format_log_line(message, telegram_user_id=telegram_user_id, **fields))


def log_exception(logger, message, exc, telegram_user_id=None, **fields):
    error_fields = dict(fields)
    error_fields["error"] = f"{type(exc).__name__}: {exc}"
    logger.error(_format_log_line(message, telegram_user_id=telegram_user_id, **error_fields))
