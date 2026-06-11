import asyncio
import csv
import html
import io
import math
import os
import re
import traceback
import urllib.parse
from dataclasses import dataclass

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


@dataclass
class PlacesLoadStatus:
    source: str
    error_message: str | None = None
    error_details: str | None = None
    places_count: int = 0

    @property
    def has_error(self):
        return self.error_message is not None

    @property
    def has_fallback(self):
        return self.source == "disk_cache" or (
            self.source == "memory_cache" and self.has_error
        )


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
_coords_cache = {}
_coords_task = None
_places_status = PlacesLoadStatus(source="empty", places_count=0)


def _get_places_cache_path():
    from config import DATABASE_PATH

    return os.path.join(os.path.dirname(DATABASE_PATH) or ".", "places_cache.csv")


def _copy_places(places):
    return [dict(place) for place in places]


def _format_exception_details(exc):
    summary = f"{type(exc).__name__}: {exc}"
    details = []
    root_cause = exc.__cause__ or exc
    for line in traceback.format_exception_only(type(root_cause), root_cause):
        cleaned = line.strip()
        if cleaned and cleaned not in details:
            details.append(cleaned)
    if summary not in details:
        details.insert(0, summary)
    return "\n".join(details[:3])


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


def _parse_places_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    _validate_columns(reader.fieldnames)

    return [
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


async def fetch_places_from_source():
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

    return _parse_places_csv(text)


def load_places_from_disk_cache():
    cache_path = _get_places_cache_path()
    try:
        with open(cache_path, encoding="utf-8", newline="") as cache_file:
            return _parse_places_csv(cache_file.read())
    except FileNotFoundError as exc:
        raise PlacesLoadError("No saved places cache found") from exc
    except OSError as exc:
        raise PlacesLoadError("Failed to read saved places cache") from exc


def save_places_to_disk_cache(places):
    cache_path = _get_places_cache_path()
    directory = os.path.dirname(cache_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    fieldnames = []
    for place in places:
        for key in place.keys():
            if key not in fieldnames and key != "_coords":
                fieldnames.append(key)
    for column in REQUIRED_PLACE_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)

    temp_path = f"{cache_path}.tmp"
    with open(temp_path, "w", encoding="utf-8", newline="") as cache_file:
        writer = csv.DictWriter(cache_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for place in places:
            writer.writerow(place)
    os.replace(temp_path, cache_path)


async def _enrich_places_with_coords(places):
    async with aiohttp.ClientSession() as geo_session:
        for place in places:
            address = place.get("Адрес", "")
            if not address:
                place["_coords"] = None
                continue

            if address not in _coords_cache:
                _coords_cache[address] = await _geocode_address(geo_session, address)
                await asyncio.sleep(1.1)

            place["_coords"] = _coords_cache[address]


def schedule_places_geocoding(places=None):
    global _coords_task

    if places is None:
        places = _places_cache

    if _coords_task and not _coords_task.done():
        _coords_task.cancel()

    _coords_task = asyncio.create_task(_enrich_places_with_coords(places))
    return _coords_task


async def get_places():
    return _places_cache


async def ensure_places_loaded():
    if _places_cache:
        return _places_cache

    try:
        cached_places = load_places_from_disk_cache()
        return _set_places_state(cached_places, "disk_cache")
    except PlacesLoadError:
        pass

    places, _ = await reload_places()
    return places


def get_places_count():
    return len(_places_cache)


def get_places_load_status():
    return PlacesLoadStatus(
        source=_places_status.source,
        error_message=_places_status.error_message,
        error_details=_places_status.error_details,
        places_count=_places_status.places_count,
    )


def _set_places_state(places, source, error_message=None, error_details=None):
    global _places_cache, _places_status

    _places_cache = _copy_places(places)
    _places_status = PlacesLoadStatus(
        source=source,
        error_message=error_message,
        error_details=error_details,
        places_count=len(_places_cache),
    )
    schedule_places_geocoding(_places_cache)
    return _places_cache


async def reload_places():
    try:
        places = await fetch_places_from_source()
    except PlacesLoadError as exc:
        error_details = _format_exception_details(exc)
        if _places_cache:
            places = _set_places_state(
                _places_cache,
                "memory_cache",
                error_message=str(exc),
                error_details=error_details,
            )
            return places, get_places_load_status()

        try:
            cached_places = load_places_from_disk_cache()
        except PlacesLoadError:
            places = _set_places_state(
                [],
                "empty",
                error_message=str(exc),
                error_details=error_details,
            )
            return places, get_places_load_status()

        places = _set_places_state(
            cached_places,
            "disk_cache",
            error_message=str(exc),
            error_details=error_details,
        )
        return places, get_places_load_status()

    try:
        save_places_to_disk_cache(places)
    except OSError:
        pass
    places = _set_places_state(places, "google_sheets")
    return places, get_places_load_status()


async def initialize_places():
    try:
        cached_places = load_places_from_disk_cache()
        places = _set_places_state(cached_places, "disk_cache")
        return places, get_places_load_status()
    except PlacesLoadError:
        return await reload_places()


def _sort_walking_route(places, metro):
    anchor = metro[0] if isinstance(metro, list) else metro
    metro_coords = METRO_COORDS.get(anchor)
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


def _select_mix_places(places, max_count, metro):
    by_category = {}
    for place in places:
        parts = _split_classification(place.get("классификация", ""))
        category = parts[0] if parts else ""
        by_category.setdefault(category, []).append(place)

    selected = []
    buckets = [list(bucket) for bucket in by_category.values()]
    while len(selected) < max_count:
        buckets = [b for b in buckets if b]
        if not buckets:
            break
        for bucket in buckets:
            if len(selected) >= max_count:
                break
            selected.append(bucket.pop(0))

    return _sort_walking_route(selected, metro)


def filter_places(places, metro, theme_key, exclude_ids=None):
    metro_set = set(metro) if isinstance(metro, list) else {metro}
    theme_val = THEMES.get(theme_key)
    result = []
    for place in places:
        place_class = place.get("классификация", "").lower()
        if _place_key(place) not in metro_set:
            continue
        if theme_val is None:
            result.append(place)
        elif theme_val in place_class:
            result.append(place)

    if exclude_ids:
        fresh = [p for p in result if p.get("_sheet_row_number") not in exclude_ids]
        if fresh:
            result = fresh

    if theme_val is None:
        return _select_mix_places(result, MAX_ROUTE_PLACES, metro)

    result = _sort_walking_route(result, metro)
    return result[:MAX_ROUTE_PLACES]


def _place_key(place):
    metro = place.get("Метро", "")
    return metro if metro else place.get("Район", "")


def get_available_themes(places, metro):
    metro_set = set(metro) if isinstance(metro, list) else {metro}
    available = []
    for theme_label, theme_val in THEMES.items():
        if theme_val is None:
            count = sum(1 for place in places if _place_key(place) in metro_set)
            if count > 0:
                available.append(theme_label)
            continue

        count = sum(
            1
            for place in places
            if _place_key(place) in metro_set
            and theme_val in place.get("классификация", "").lower()
        )
        if count > 0:
            available.append(theme_label)
    return available


def format_route(places, metro, theme):
    text = f"🗺 {theme} · {metro}\n\n"
    for place in places:
        name = html.escape(place.get("Название", ""))
        address_raw = place.get("Адрес", "")
        address = html.escape(address_raw)
        description = html.escape(place.get("Описание", ""))
        check = place.get("Чек", "")
        coords = place.get("_coords")
        if coords:
            map_url = f"https://yandex.ru/maps/?ll={coords[1]},{coords[0]}&pt={coords[1]},{coords[0]}&z=17"
        else:
            map_url = f"https://yandex.ru/maps/?text={urllib.parse.quote(address_raw)}"
        text += f"<b>{name}</b>\n"
        text += f"📍 <i>{address}</i> <a href=\"{map_url}\">на карте</a>\n"
        if check and check.strip():
            text += f"💰 {html.escape(check)}\n"
        text += f"{description}\n\n"
        text += "\n"
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
