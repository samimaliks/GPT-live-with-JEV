"""Current conditions from Open-Meteo. No API key."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_CITY = "Karachi"

_WEATHER_ASK = re.compile(
    r"\b(?:what(?:'s| is|s)?|how(?:'s| is|s)?|tell me|check|give me|want|need)\b[\s\S]{0,80}\bweather\b"
    r"|\bweather\b\s+(?:in|at|for|of|around|near|like|today|tonight|now)\b",
    re.IGNORECASE,
)
_WEATHER_WORD = re.compile(r"\bweather\b", re.IGNORECASE)
_PLACE_INTRO = re.compile(
    r"\b(?:in|at|for|of|around|near|and)\s+",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z'.-]*|[\u0600-\u06FF]{2,}")
_NOT_CITY = frozenset(
    {
        "a", "ah", "an", "and", "about", "also", "at", "bad", "can", "check", "city",
        "current", "currently", "for", "get", "give", "good", "here", "how", "hows",
        "i", "in", "is", "it", "its", "just", "like", "local", "me", "my", "need",
        "nice", "no", "not", "now", "of", "ok", "okay", "on", "or", "our", "outside",
        "love", "lovely", "please", "real", "right", "some", "tell", "that", "the", "there", "this",
        "to", "today", "todays", "tomorrow", "tonight", "uh", "um", "want", "weather",
        "what", "whats", "why", "work", "yeah", "yes", "you", "your",
    }
)
_ARTICLES = frozenset({"a", "an", "the"})
_SCRIPT_PLACES = {
    "لاہور": "Lahore",
    "لاهور": "Lahore",
    "کراچی": "Karachi",
    "کراچي": "Karachi",
    "اسلامآباد": "Islamabad",
}

# WMO weather interpretation codes used by Open-Meteo.
_CONDITIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Freezing drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Freezing rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherError(Exception):
    """The city or the current forecast could not be read."""


def _token(word: str) -> str:
    return re.sub(r"'s$", "", word.lower()).replace("'", "")


def _title_city(words: list[str]) -> str:
    cleaned = [re.sub(r"'s$", "", word, flags=re.IGNORECASE) for word in words]
    cleaned = [word for word in cleaned if len(word) >= 2 and _token(word) != "weather"]
    if not cleaned:
        return ""
    if all(re.fullmatch(r"[A-Za-z'.-]+", word) for word in cleaned):
        return " ".join(cleaned).title()
    return " ".join(cleaned)


def _place_words(words: list[str]) -> str:
    """Take the place name and stop at filler or another 'weather'."""
    chosen: list[str] = []
    for word in words:
        token = _token(word)
        if token == "weather":
            break
        if token in _ARTICLES and not chosen:
            continue
        if token in _NOT_CITY:
            break
        chosen.append(word)
        if len(chosen) == 3:
            break
    return _title_city(chosen)


def _hits(text: str) -> list[re.Match[str]]:
    return list(_WEATHER_WORD.finditer(text))


def _city_before_hit(text: str, hit: re.Match[str], previous_end: int) -> str:
    """Place spoken just before weather, as in 'Lahore weather' or 'لاہور weather'."""
    start = max(previous_end, hit.start() - 40)
    words = _TOKEN.findall(text[start:hit.start()])
    chosen: list[str] = []
    for word in reversed(words):
        token = _token(word)
        if token == "weather" or token in _NOT_CITY:
            break
        chosen.append(word)
        if re.search(r"[\u0600-\u06FF]", word) or len(chosen) == 3:
            break
    return _title_city(list(reversed(chosen)))


def _label_place(city: str) -> str:
    return _SCRIPT_PLACES.get(city, city)


def _places_after(window: str) -> list[str]:
    """Every place after a weather ask, including 'and in Lahore'."""
    matches = list(_PLACE_INTRO.finditer(window))
    places: list[str] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(window)
        chunk = window[match.end():end]
        chunk = chunk.split(",")[0]
        chunk = re.sub(r"[?.!].*", "", chunk)
        city = _label_place(_place_words(_TOKEN.findall(chunk)))
        key = city.lower()
        if city and key not in seen:
            seen.add(key)
            places.append(city)
    return places


def weather_places(text: str) -> list[str]:
    """Every place in the latest weather ask. Karachi only when none is named."""
    hits = _hits(text)
    if not hits:
        return []
    hit = hits[-1]
    previous_end = hits[-2].end() if len(hits) > 1 else 0
    places: list[str] = []
    seen: set[str] = set()
    before = _label_place(_city_before_hit(text, hit, previous_end))
    if before:
        places.append(before)
        seen.add(before.lower())
    window = text[hit.end(): hit.end() + 280]
    window = _WEATHER_WORD.split(window, maxsplit=1)[0]
    for city in _places_after(window):
        key = city.lower()
        if key not in seen:
            seen.add(key)
            places.append(city)
    if places:
        return places
    if _WEATHER_ASK.search(text):
        return [DEFAULT_CITY]
    return []


def wants_weather(text: str) -> bool:
    if _WEATHER_ASK.search(text):
        return True
    places = weather_places(text)
    return bool(places) and places != [DEFAULT_CITY]


def weather_city(text: str) -> str:
    """Latest place the caller named. Karachi only when they name none."""
    places = weather_places(text)
    return places[-1] if places else DEFAULT_CITY


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "personal-agent/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise WeatherError("Open-Meteo returned an unexpected response.")
    return payload


def _temperature(value: float, unit: str) -> str:
    shown = f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"
    label = "°C" if unit in {"°C", "C", "celsius"} else unit or "°C"
    return f"{shown}{label}"


def current_weather(city: str) -> dict[str, str]:
    """Geocode the city, then read the current temperature and conditions."""
    query = urllib.parse.urlencode({"name": city, "count": 1, "language": "en", "format": "json"})
    found = _get_json(f"{GEOCODE_URL}?{query}")
    places = found.get("results") or []
    if not places:
        raise WeatherError(f"No place named {city} was found.")
    place = places[0]
    name = str(place.get("name") or city)
    latitude = place.get("latitude")
    longitude = place.get("longitude")
    if latitude is None or longitude is None:
        raise WeatherError(f"No coordinates were found for {name}.")
    forecast_query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        }
    )
    forecast = _get_json(f"{FORECAST_URL}?{forecast_query}")
    current = forecast.get("current") or {}
    temperature = current.get("temperature_2m")
    code = current.get("weather_code")
    if temperature is None or code is None:
        raise WeatherError("The forecast did not include current conditions.")
    unit = str((forecast.get("current_units") or {}).get("temperature_2m") or "°C")
    try:
        code_number = int(code)
    except (TypeError, ValueError) as exc:
        raise WeatherError("The forecast did not include a weather code.") from exc
    conditions = _CONDITIONS.get(code_number, "Unlisted conditions")
    return {
        "city": name,
        "temperature": _temperature(float(temperature), unit),
        "conditions": conditions,
        "icon": _icon_for(code_number),
    }


def _icon_for(code: int) -> str:
    if code == 0:
        return "clear"
    if code in {1, 2}:
        return "partly"
    if code == 3:
        return "cloud"
    if code in {45, 48}:
        return "fog"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "storm"
    if 51 <= code <= 67 or code in {80, 81, 82}:
        return "rain"
    return "cloud"
