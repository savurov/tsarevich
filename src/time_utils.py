from datetime import datetime, timezone
from zoneinfo import ZoneInfo


MSK_TZ = ZoneInfo("Europe/Moscow")
MONTHS_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def format_utc_timestamp_msk(value):
    if not value:
        return "неизвестно"

    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return value

    msk_dt = dt.astimezone(MSK_TZ)
    return (
        f"{msk_dt.day} {MONTHS_RU[msk_dt.month]} "
        f"{msk_dt.hour:02d}:{msk_dt.minute:02d}"
    )
