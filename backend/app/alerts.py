"""Weather-linked threat rules. Thresholds are indicative; calibrate them per crop and region
with your state agriculture university and IMD agromet advisories before real use."""
from datetime import date

LEVEL_RANK = {"urgent": 3, "warning": 2, "watch": 1}


def _split(days, today_iso):
    past = [d for d in days if d["date"] < today_iso]
    fut = [d for d in days if d["date"] >= today_iso]
    return past, fut


def _alert(kind, level, title, message, actions, when=""):
    return {"id": f"{kind}:{level}", "type": kind, "level": level, "title": title,
            "message": message, "actions": actions, "when": when}


def evaluate(weather: dict, crop: dict, stage: dict, today: date):
    days = weather["days"]
    past, fut = _split(days, today.isoformat())
    next3, next5 = fut[:3], fut[:5]
    sensitive = stage.get("name") in crop.get("sensitive", [])
    out = []
    stage_note = f" Your crop is at the {stage['name'].lower()} stage" + (", which is a sensitive stage." if sensitive else ".")

    # 1. fungal disease risk: humid and rainy spell at moderate temperature
    humid = [d for d in next3 if d["rh"] is not None and d["rh"] >= 80 and d["tmax"] is not None and 20 <= d["tmax"] <= 33]
    wet = [d for d in humid if d["rain"] >= 2]
    if len(humid) >= 2:
        level = "warning" if len(wet) >= 2 else "watch"
        out.append(_alert(
            "fungal", level, "Fungal disease risk in the next 3 days",
            f"Humidity is forecast at {max(d['rh'] for d in humid):.0f}% with {sum(d['rain'] for d in next3):.0f} mm rain." + stage_note,
            ["Inspect leaves tomorrow, especially the lower ones, and upload photos in the Checkup tab.",
             "Avoid watering in the evening and keep rows open for air flow.",
             "Ask your agriculture officer about preventive options before the spell starts."],
            "Next 3 days"))

    # 2. heavy rain
    if next3:
        peak = max(next3, key=lambda d: d["rain"])
        if peak["rain"] >= 65:
            lvl = "urgent"
        elif peak["rain"] >= 35:
            lvl = "warning"
        elif peak["rain"] >= 20:
            lvl = "watch"
        else:
            lvl = None
        if lvl:
            out.append(_alert(
                "heavy_rain", lvl, "Heavy rain expected",
                f"About {peak['rain']:.0f} mm of rain is forecast on {peak['date']}. Fertiliser and sprays applied now can wash away.",
                ["Clear drain channels so water does not stand in the field.",
                 "Delay fertiliser and spraying until the rain has passed.",
                 "Check for waterlogged patches after the rain."], peak["date"]))

    # 3. heat
    hot = [d for d in next3 if d["tmax"] is not None and d["tmax"] >= crop["heat_c"]]
    if hot:
        peak = max(hot, key=lambda d: d["tmax"])
        if sensitive and peak["tmax"] >= crop["heat_c"] + 3:
            lvl = "urgent"
        elif sensitive or len(hot) >= 2:
            lvl = "warning"
        else:
            lvl = "watch"
        out.append(_alert(
            "heat", lvl, "Heat stress risk",
            f"Maximum temperature may reach {peak['tmax']:.0f}°C on {peak['date']}." + stage_note,
            ["Irrigate lightly in the early morning or evening, not at midday.",
             "Mulch to cool the soil and keep moisture.",
             "Avoid spraying in the heat of the day."], peak["date"]))

    # 4. cold or frost
    cold = [d for d in next3 if d["tmin"] is not None and d["tmin"] <= crop["cold_c"]]
    if cold:
        low = min(cold, key=lambda d: d["tmin"])
        lvl = "urgent" if low["tmin"] <= 2 else ("warning" if sensitive else "watch")
        out.append(_alert(
            "cold", lvl, "Cold damage risk",
            f"Night temperature may drop to {low['tmin']:.0f}°C on {low['date']}.",
            ["Cover young plants overnight where you can.", "A light irrigation before a cold night can reduce damage."], low["date"]))

    # 5. dry spell
    rain14 = sum(d["rain"] for d in past[-14:]) if len(past) >= 7 else None
    rain_next5 = sum(d["rain"] for d in next5)
    if rain14 is not None and rain14 < 10 and rain_next5 < 5:
        lvl = "warning" if (sensitive or rain14 < 3) else "watch"
        out.append(_alert(
            "dry_spell", lvl, "Dry spell: plan irrigation",
            f"Only {rain14:.0f} mm of rain in the last 14 days and little is forecast." + stage_note,
            ["Check soil moisture 10 cm below the surface and irrigate if it is dry.",
             "Irrigate in the early morning or evening and mulch to hold moisture."], "Next 5 days"))

    # 6. wind
    windy = max(fut[:3], key=lambda d: d["wind"], default=None)
    if windy and windy["wind"] >= 40:
        out.append(_alert(
            "wind", "urgent" if windy["wind"] >= 60 else "warning", "Strong wind expected",
            f"Winds up to {windy['wind']:.0f} km/h are forecast on {windy['date']}.",
            ["Support tall or heavily loaded plants.", "Do not spray on windy days."], windy["date"]))

    out.sort(key=lambda a: -LEVEL_RANK[a["level"]])
    return out
