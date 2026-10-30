"""Weather from Open-Meteo (free, no key) with a demo fallback."""
import logging
import random
from datetime import date, timedelta

import requests

log = logging.getLogger("weather")

WMO = {
    0: ("Clear sky", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "cloud-sun"), 3: ("Overcast", "cloud"),
    45: ("Fog", "fog"), 48: ("Fog", "fog"), 51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"), 61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Violent showers", "rain"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm", "storm"), 99: ("Thunderstorm", "storm"),
}


def _wmo(code):
    if code in WMO:
        return WMO[code]
    if code is None:
        return ("", "cloud")
    if 51 <= code <= 57:
        return ("Drizzle", "drizzle")
    if 61 <= code <= 67 or 80 <= code <= 82:
        return ("Rain", "rain")
    if code >= 95:
        return ("Thunderstorm", "storm")
    return ("Cloudy", "cloud")


def fetch_live(lat: float, lng: float, today: date):
    params = {
        "latitude": round(lat, 4), "longitude": round(lng, 4),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "hourly": "relative_humidity_2m",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
        "past_days": 14, "forecast_days": 7, "timezone": "auto",
    }
    last = None
    for _ in range(2):
        try:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=12)
            r.raise_for_status()
            j = r.json()
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
    else:
        raise RuntimeError(f"Open-Meteo request failed: {last}")

    d = j["daily"]
    rh_by_day = {}
    for t, v in zip(j["hourly"]["time"], j["hourly"]["relative_humidity_2m"]):
        if v is not None:
            rh_by_day.setdefault(t[:10], []).append(v)
    days = []
    for i, ds in enumerate(d["time"]):
        rh = rh_by_day.get(ds)
        days.append({
            "date": ds,
            "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
            "rain": d["precipitation_sum"][i] or 0.0, "wind": d["wind_speed_10m_max"][i] or 0.0,
            "rh": round(sum(rh) / len(rh), 1) if rh else None,
        })
    cur = j.get("current") or {}
    label, icon = _wmo(cur.get("weather_code"))
    now = {
        "temp": cur.get("temperature_2m"), "rh": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"), "label": label, "icon": icon,
    }
    return {"source": "open-meteo", "now": now, "days": days}


def demo_weather(farm: dict, today: date):
    scenario = farm.get("scenario") or "healthy"
    rnd = random.Random(int(farm["id"]) * 31 + today.toordinal())
    days = []
    for off in range(-14, 7):
        dt = today + timedelta(days=off)
        tmax, tmin, rain, rh, wind = 31 + rnd.uniform(-2, 2), 21 + rnd.uniform(-2, 2), 0.0, 62 + rnd.uniform(-8, 8), 10 + rnd.uniform(0, 8)
        if scenario == "healthy" and off % 4 == 0:
            rain = rnd.uniform(3, 12)
            rh += 12
        if scenario == "nitrogen":
            if off in (-12, -11):
                rain = rnd.choice([62, 48])
            elif off in (-6, -3):
                rain = rnd.uniform(6, 14)
        if scenario == "water":
            tmax = 35 + rnd.uniform(-1, 2.5) if off <= 0 else 36 + rnd.uniform(-1, 2)
            rh = 40 + rnd.uniform(-5, 6)
        if scenario == "disease":
            if off >= -5:
                rain = rnd.uniform(5, 14) if off % 2 == 0 else rnd.uniform(0, 4)
                rh = 86 + rnd.uniform(-3, 6)
                tmax, tmin = 28 + rnd.uniform(-1, 1.5), 22 + rnd.uniform(-1, 1)
        if scenario == "late" and off % 5 == 0:
            rain = rnd.uniform(2, 8)
        days.append({"date": dt.isoformat(), "tmax": round(tmax, 1), "tmin": round(tmin, 1), "rain": round(rain, 1),
                     "wind": round(wind, 1), "rh": round(min(98, rh), 1)})
    t = next(d for d in days if d["date"] == today.isoformat())
    wet = t["rain"] > 3
    now = {"temp": round(t["tmax"] - 3, 1), "rh": t["rh"], "wind": t["wind"],
           "label": "Rain showers" if wet else "Partly cloudy", "icon": "rain" if wet else "cloud-sun"}
    return {"source": "demo", "now": now, "days": days}


def get(farm: dict, today: date):
    try:
        return fetch_live(farm["lat"], farm["lng"], today), None
    except Exception as exc:  # noqa: BLE001
        log.warning("weather fallback: %s", exc)
        return demo_weather(farm, today), f"Live weather unavailable ({str(exc)[:80]}). Showing sample weather."


def fetch_history(lat: float, lng: float, start: date, end: date):
    """Daily history from the Open-Meteo archive (about 2 days behind real time)."""
    params = {
        "latitude": round(lat, 4), "longitude": round(lng, 4), "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": "auto",
    }
    r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=20)
    r.raise_for_status()
    d = r.json().get("daily") or {}
    days = []
    for i, ds in enumerate(d.get("time", [])):
        tmax, tmin, rain = d["temperature_2m_max"][i], d["temperature_2m_min"][i], d["precipitation_sum"][i]
        if tmax is None and rain is None:
            continue
        days.append({"date": ds, "tmax": tmax, "tmin": tmin, "rain": rain or 0.0})
    return days
