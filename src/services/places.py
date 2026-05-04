import csv
import io
from urllib.parse import quote_plus

import aiohttp

from config import (
    MAX_ROUTE_PLACES,
    PLACES_REQUEST_TIMEOUT_SECONDS,
    REQUIRED_PLACE_COLUMNS,
    SHEET_URL,
    THEMES,
)


class PlacesLoadError(Exception):
    pass


_places_cache = []


def _normalize_place(raw_place):
    return {key: (value or "").strip() for key, value in raw_place.items()}


def _validate_columns(fieldnames):
    if not fieldnames:
        raise PlacesLoadError("Google Sheets returned an empty CSV header")

    missing_columns = [
        column for column in REQUIRED_PLACE_COLUMNS if column not in fieldnames
    ]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise PlacesLoadError(f"Missing required CSV columns: {missing}")


async def _load_places():
    try:
        timeout = aiohttp.ClientTimeout(total=PLACES_REQUEST_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(SHEET_URL) as resp:
                resp.raise_for_status()
                text = await resp.text()
    except aiohttp.ClientError as exc:
        raise PlacesLoadError("Failed to load places from Google Sheets") from exc
    except TimeoutError as exc:
        raise PlacesLoadError("Google Sheets request timed out") from exc

    reader = csv.DictReader(io.StringIO(text))
    _validate_columns(reader.fieldnames)

    places = [
        _normalize_place(place)
        for place in reader
        if any((value or "").strip() for value in place.values())
    ]
    return places


async def get_places():
    if not _places_cache:
        raise PlacesLoadError("Places cache is empty. Load data before handling requests")
    return _places_cache


async def reload_places():
    global _places_cache

    places = await _load_places()
    _places_cache = places
    return places


def filter_places(places, metro, theme_key):
    theme_val = THEMES.get(theme_key)
    result = []
    for place in places:
        place_metro = place.get("Метро", "")
        place_class = place.get("классификация", "").lower()
        if place_metro != metro:
            continue
        if theme_val is None:
            result.append(place)
        elif theme_val in place_class:
            result.append(place)
    return result[:MAX_ROUTE_PLACES]


def get_available_themes(places, metro):
    available = []
    for theme_label, theme_val in THEMES.items():
        if theme_val is None:
            count = sum(1 for place in places if place.get("Метро", "") == metro)
            if count > 0:
                available.append(theme_label)
            continue

        count = sum(
            1
            for place in places
            if place.get("Метро", "") == metro
            and theme_val in place.get("классификация", "").lower()
        )
        if count > 0:
            available.append(theme_label)
    return available


def format_route(places, metro, theme):
    text = f"🗺 {theme} · {metro}\n\n"
    for index, place in enumerate(places, 1):
        name = place.get("Название", "")
        address = place.get("Адрес", "")
        description = place.get("Описание", "")
        check = place.get("Чек", "")
        maps_query = quote_plus(f"{address} Санкт-Петербург")
        maps_url = f"https://yandex.ru/maps/?text={maps_query}"
        text += f"📍 {index}. {name}\n"
        text += f"🏠 {address}\n"
        if check and check.strip().lower() == "бесплатно":
            text += "💚 Бесплатно\n"
        elif check and check.strip():
            text += f"💰 {check}\n"
        text += f"{description}\n"
        text += f"🗺 {maps_url}\n\n"
        text += "—" * 20 + "\n\n"
    return text
