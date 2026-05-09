import asyncio
import csv
import html
import io
import math
import re
from urllib.parse import quote_plus

import aiohttp

from config import (
    DISTRICTS,
    MAX_ROUTE_PLACES,
    METRO_COORDS,
    PLACES_REQUEST_TIMEOUT_SECONDS,
    REQUIRED_PLACE_COLUMNS,
    SHEET_URL,
    THEMES,
)


class PlacesLoadError(Exception):
    pass


def _haversine_meters(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


async def _geocode_address(session: aiohttp.ClientSession, address: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": f"{address} Санкт-Петербург", "format": "json", "limit": 1}
    headers = {"User-Agent": "dro4ka-tg-bot/1.0"}
    try:
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            data = await resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


_places_cache = []


def _normalize_place(raw_place):
    return {key: (value or "").strip() for key, value in raw_place.items()}


def _build_metro_lookup():
    lookup = {}
    for metros in DISTRICTS.values():
        for metro in metros:
            lookup[metro.strip().lower()] = metro
    return lookup


def _build_theme_lookup():
    lookup = {}
    for theme_value in THEMES.values():
        if theme_value:
            lookup[theme_value.strip().lower()] = theme_value
    return lookup


METRO_LOOKUP = _build_metro_lookup()
THEME_LOOKUP = _build_theme_lookup()


def _validate_columns(fieldnames):
    if not fieldnames:
        raise PlacesLoadError("Google Sheets returned an empty CSV header")

    missing_columns = [
        column for column in REQUIRED_PLACE_COLUMNS if column not in fieldnames
    ]
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise PlacesLoadError(f"Missing required CSV columns: {missing}")


def _split_classification(value):
    return [part.strip().lower() for part in re.split(r"[,;/]+", value) if part.strip()]


def _normalize_metro(value):
    if not value:
        return ""
    return METRO_LOOKUP.get(value.strip().lower(), value.strip())


def _normalize_classification(value):
    if not value:
        return ""

    normalized_parts = []
    for part in _split_classification(value):
        normalized_parts.append(THEME_LOOKUP.get(part, part))
    return ", ".join(normalized_parts)


def _normalize_domain_values(place):
    normalized_place = dict(place)
    normalized_place["Метро"] = _normalize_metro(place.get("Метро", ""))
    normalized_place["классификация"] = _normalize_classification(
        place.get("классификация", "")
    )
    return normalized_place


async def _load_places():
    try:
        timeout = aiohttp.ClientTimeout(total=PLACES_REQUEST_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
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
        _normalize_domain_values(
            _normalize_place(
                {
                    **place,
                    "_sheet_row_number": str(sheet_row_number),
                }
            )
        )
        for sheet_row_number, place in enumerate(reader, start=2)
        if any((value or "").strip() for value in place.values())
    ]

    async with aiohttp.ClientSession() as geo_session:
        for place in places:
            address = place.get("Адрес", "")
            if address:
                coords = await _geocode_address(geo_session, address)
                place["_coords"] = coords
            else:
                place["_coords"] = None
            await asyncio.sleep(1.1)

    return places


async def get_places():
    if not _places_cache:
        raise PlacesLoadError("Places cache is empty. Load data before handling requests")
    return _places_cache


def get_places_count():
    return len(_places_cache)


async def reload_places():
    global _places_cache

    places = await _load_places()
    _places_cache = places
    return places


def _sort_walking_route(places, metro):
    metro_coords = METRO_COORDS.get(metro)
    with_coords = [p for p in places if p.get("_coords")]
    without_coords = [p for p in places if not p.get("_coords")]

    if not metro_coords or not with_coords:
        return places

    current = metro_coords
    remaining = list(with_coords)
    route = []
    while remaining:
        nearest = min(
            remaining,
            key=lambda p: _haversine_meters(current[0], current[1], p["_coords"][0], p["_coords"][1]),
        )
        route.append(nearest)
        current = nearest["_coords"]
        remaining.remove(nearest)

    return route + without_coords


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
    result = _sort_walking_route(result, metro)
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
        name = html.escape(place.get("Название", ""))
        address = html.escape(place.get("Адрес", ""))
        description = html.escape(place.get("Описание", ""))
        check = place.get("Чек", "")
        maps_query = quote_plus(f"{place.get('Адрес', '')} Санкт-Петербург")
        maps_url = f"https://yandex.ru/maps/?text={maps_query}"
        text += f"📍 {index}. {name}\n"
        text += f"🏠 {address}\n"
        if check and check.strip().lower() == "бесплатно":
            text += "💚 Бесплатно\n"
        elif check and check.strip():
            text += f"💰 {html.escape(check)}\n"
        text += f"{description}\n"
        text += f'🗺 <a href="{maps_url}">посмотреть на карте</a>\n\n'
        text += "—" * 20 + "\n\n"
    return text


def _get_allowed_metros():
    return set(METRO_LOOKUP.values())


def _get_allowed_theme_values():
    return set(THEME_LOOKUP.values())


def validate_places(places):
    warnings = []
    allowed_metros = _get_allowed_metros()
    allowed_theme_values = _get_allowed_theme_values()

    for place in places:
        row_number = place.get("_sheet_row_number", "?")
        metro = place.get("Метро", "")
        classification = place.get("классификация", "")

        if not metro:
            warnings.append(
                {
                    "row_number": row_number,
                    "field": "Метро",
                    "value": "—",
                    "reason": "метро отсутствует",
                }
            )
        elif metro not in allowed_metros:
            warnings.append(
                {
                    "row_number": row_number,
                    "field": "Метро",
                    "value": metro,
                    "reason": "неизвестное метро",
                }
            )

        if not classification:
            warnings.append(
                {
                    "row_number": row_number,
                    "field": "классификация",
                    "value": "—",
                    "reason": "классификация отсутствует",
                }
            )

        for part in _split_classification(classification):
            if part not in allowed_theme_values:
                warnings.append(
                    {
                        "row_number": row_number,
                        "field": "классификация",
                        "value": part,
                        "reason": "неизвестная классификация",
                    }
                )

    return warnings
