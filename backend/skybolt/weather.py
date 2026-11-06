"""Weather via Open-Meteo (free, no API key). Backend fetches + caches; the UI only talks to us."""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .config import Settings

router = APIRouter(prefix="/api/weather", tags=["weather"])
TTL_SECONDS = 15 * 60


def fetch_open_meteo(s: Settings, units: str) -> dict:
    imperial = units == "imperial"
    q = urllib.parse.urlencode({
        "latitude": s.lat, "longitude": s.lon, "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=10) as r:
        return json.load(r)


def normalize(raw: dict, s: Settings, units: str) -> dict:
    cur, hr, dy = raw["current"], raw["hourly"], raw["daily"]
    start = next((i for i, t in enumerate(hr["time"]) if t >= cur["time"][:13] + ":00"), 0)
    hourly = [
        {"time": hr["time"][i], "temp": round(hr["temperature_2m"][i]), "code": hr["weather_code"][i],
         "precip": hr["precipitation_probability"][i]}
        for i in range(start, min(start + 12, len(hr["time"])))
    ]
    daily = [
        {"date": dy["time"][i], "code": dy["weather_code"][i], "high": round(dy["temperature_2m_max"][i]),
         "low": round(dy["temperature_2m_min"][i]), "precip": dy["precipitation_probability_max"][i],
         "sunrise": dy["sunrise"][i], "sunset": dy["sunset"][i]}
        for i in range(len(dy["time"]))
    ]
    imperial = units == "imperial"
    return {
        "location": s.location_name,
        "units": {"temp": "°F" if imperial else "°C", "wind": "mph" if imperial else "km/h"},
        "current": {"temp": round(cur["temperature_2m"]), "feels_like": round(cur["apparent_temperature"]),
                    "humidity": cur["relative_humidity_2m"], "wind": round(cur["wind_speed_10m"]),
                    "code": cur["weather_code"], "is_day": bool(cur["is_day"])},
        "hourly": hourly,
        "daily": daily,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "stale": False,
    }


@router.get("")
def get_weather(request: Request, units: Literal["imperial", "metric"] | None = Query(None)):
    st = request.app.state
    units = units or st.settings.units
    cache = st.weather_cache.setdefault(units, {})
    if cache.get("data") and time.time() - cache["at"] < TTL_SECONDS:
        return cache["data"]
    try:
        data = normalize(st.weather_fetch(st.settings, units), st.settings, units)
    except Exception:
        if cache.get("data"):  # offline: serve last good data, flagged stale
            return {**cache["data"], "stale": True}
        raise HTTPException(502, "weather unavailable")
    cache.update(data=data, at=time.time())
    return data
