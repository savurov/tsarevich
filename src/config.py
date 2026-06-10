import os


def get_required_env(name):
    value = os.getenv(name)
    if value:
        return value
    raise ValueError(f"Missing required environment variable: {name}")


def get_database_path():
    database_path = os.getenv("DATABASE_PATH")
    if database_path:
        return database_path

    volume_mount_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if volume_mount_path:
        return os.path.join(volume_mount_path, "database.sqlite3")

    return "database.sqlite3"


TOKEN = get_required_env("TOKEN")
SHEET_ID = get_required_env("SHEET_ID")
PAYMENT_PROVIDER_TOKEN = get_required_env("PAYMENT_PROVIDER_TOKEN")
SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=419935683"
)


DATABASE_PATH = get_database_path()
PAYMENT_CURRENCY = "RUB"
PAYMENT_VAT_CODE = 1
PLACES_REQUEST_TIMEOUT_SECONDS = 10
MAX_ROUTE_PLACES = 5
REQUIRED_PLACE_COLUMNS = ("Метро", "классификация", "Название", "Адрес")

PAYMENT_PLANS = {
    "1hour": {
        "label": "60 ₽ — 1 час",
        "title": "Доступ на 1 час",
        "description": "Маршруты и подборки мест в Петербурге на 1 час.",
        "price_minor_units": 6000,
        "duration_days": 1 / 24,
    },
    "1day": {
        "label": "290 ₽ — 1 день",
        "title": "Доступ на 1 день",
        "description": "Маршруты и подборки мест в Петербурге на 1 день.",
        "price_minor_units": 29000,
        "duration_days": 1,
    },
    "3days": {
        "label": "490 ₽ — 3 дня",
        "title": "Доступ на 3 дня",
        "description": "Маршруты и подборки мест в Петербурге на 3 дня.",
        "price_minor_units": 49000,
        "duration_days": 3,
    },
    "7days": {
        "label": "690 ₽ — неделя",
        "title": "Доступ на неделю",
        "description": "Маршруты и подборки мест в Петербурге на 7 дней.",
        "price_minor_units": 69000,
        "duration_days": 7,
    },
}

DISTRICTS = {
    "Василеостровский": ["Василеостровская", "Горный институт", "Приморская"],
    "Петроградский": ["Петроградская", "Спортивная", "Чкаловская"],
    "Коломна": ["Садовая", "Сенная площадь", "Технологический институт"],
}

# Districts where metro step is skipped — all stations shown combined
DISTRICTS_WITHOUT_METRO = {"Коломна"}

METRO_COORDS = {
    "Василеостровская": (59.9432, 30.2792),
    "Горный институт": (59.9308, 30.2739),
    "Приморская": (59.9534, 30.2284),
    "Петроградская": (59.9664, 30.3114),
    "Спортивная": (59.9519, 30.2917),
    "Чкаловская": (59.9601, 30.2970),
    "Садовая": (59.9270, 30.3195),
    "Сенная площадь": (59.9268, 30.3199),
    "Технологический институт": (59.9155, 30.3197),
}

THEMES = {
    "🗺 База": "база",
    "🎨 Музеи": "музей",
    "🏛 Архитектура": "архитектура",
    "🚪 Неформальное": "неформальный",
    "☕ Кофейни": "кофе",
    "🍽 Обед": "обед",
    "✨ Спешел от автора": "спешел от автора",
    "🎲 Микс": None,
}
