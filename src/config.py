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
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"
DATABASE_PATH = get_database_path()
PLACES_REQUEST_TIMEOUT_SECONDS = 10
MAX_ROUTE_PLACES = 5
REQUIRED_PLACE_COLUMNS = ("Метро", "классификация", "Название", "Адрес")

DISTRICTS = {
    "Василеостровский": ["Василеостровская", "Горный институт", "Приморская"],
    "Петроградский": ["Петроградская", "Спортивная", "Чкаловская"],
    "Коломна": ["Садовая", "Сенная площадь", "Технологический институт"],
}

METRO_COORDS = {
    "Василеостровская":          (59.9432, 30.2792),
    "Горный институт":           (59.9308, 30.2739),
    "Приморская":                (59.9534, 30.2284),
    "Петроградская":             (59.9664, 30.3114),
    "Спортивная":                (59.9519, 30.2917),
    "Чкаловская":                (59.9601, 30.2970),
    "Садовая":                   (59.9270, 30.3195),
    "Сенная площадь":            (59.9268, 30.3199),
    "Технологический институт":  (59.9155, 30.3197),
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
