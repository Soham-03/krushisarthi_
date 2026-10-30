"""Detect abnormal growth, then work out why using weather, soil, water, nutrients and photo checkups.
All thresholds are indicative starting points. Calibrate with local agronomy data."""
from datetime import date, timedelta

from . import crops

NORMAL_MIN = -12.0     # % below the expected curve that is still "normal"
ABNORMAL_BELOW = -25.0


# ------------------------------------------------------------------ growth status
def evaluate_series(crop: dict, sowing: date, obs: list, today: date):
    day = (today - sowing).days
    rows = []
    for o in obs:
        d = (date.fromisoformat(o["date"]) - sowing).days
        exp = crops.expected_ndvi(crop, d)
        rows.append({**o, "day": d, "expected": round(exp, 3),
                     "dev_pct": round((o["ndvi"] - exp) / max(exp, 0.05) * 100, 1)})
    if day < 0:
        return {"status": "not_started", "health": None, "deviation_pct": None, "series": rows, "last": None,
                "message": "Sowing date is in the future. Monitoring starts after sowing."}
    if day > crop["duration"] + 25:
        return {"status": "ended", "health": None, "deviation_pct": None, "series": rows, "last": rows[-1] if rows else None,
                "message": "This crop cycle has ended. Add a new farm or change the sowing date for the next season."}
    if not rows:
        return {"status": "no_data", "health": None, "deviation_pct": None, "series": rows, "last": None,
                "message": "No clear satellite pass yet. The next one is usually within 5 days."}

    recent = [r for r in rows if (today - date.fromisoformat(r["date"])).days <= 20][-2:] or rows[-1:]
    dev = sum(r["dev_pct"] for r in recent) / len(recent)
    status = "normal" if dev >= NORMAL_MIN else ("watch" if dev >= ABNORMAL_BELOW else "abnormal")
    # a steady fall while the crop should be growing is a warning even if the gap is small
    last3 = rows[-3:]
    if len(last3) == 3 and last3[0]["ndvi"] > last3[1]["ndvi"] > last3[2]["ndvi"] and last3[2]["expected"] >= last3[0]["expected"] - 0.02:
        if status == "normal":
            status = "watch"
    health = int(round(max(0, min(100, 100 - max(0.0, -dev) * 2))))
    last = rows[-1]
    age = (today - date.fromisoformat(last["date"])).days
    msgs = {
        "normal": "Growth is on track for this stage.",
        "watch": f"Growth is {abs(dev):.0f}% below the expected level. Keep a close eye on it.",
        "abnormal": f"Growth is {abs(dev):.0f}% below the expected level. Something is holding the crop back.",
    }
    return {"status": status, "health": health, "deviation_pct": round(dev, 1), "series": rows, "last": last,
            "age_days": age, "message": msgs[status]}


# ------------------------------------------------------------------ soil
def rate_soil(s: dict | None):
    if not s:
        return None
    def band(v, low, high):
        return "low" if v < low else ("medium" if v <= high else "high")
    out = {}
    if s.get("n") is not None:
        out["n"] = {"value": s["n"], "unit": "kg/ha", "rating": band(s["n"], 280, 560)}
    if s.get("p") is not None:
        out["p"] = {"value": s["p"], "unit": "kg/ha", "rating": band(s["p"], 10, 25)}
    if s.get("k") is not None:
        out["k"] = {"value": s["k"], "unit": "kg/ha", "rating": band(s["k"], 108, 280)}
    if s.get("oc") is not None:
        out["oc"] = {"value": s["oc"], "unit": "%", "rating": band(s["oc"], 0.5, 0.75)}
    if s.get("ph") is not None:
        v = s["ph"]
        r = "strongly acidic" if v < 5.5 else "acidic" if v < 6.5 else "neutral" if v <= 7.5 else "alkaline" if v <= 8.5 else "strongly alkaline"
        out["ph"] = {"value": v, "unit": "", "rating": r}
    if s.get("ec") is not None:
        v = s["ec"]
        out["ec"] = {"value": v, "unit": "dS/m", "rating": "normal" if v < 1 else "slightly saline" if v < 2 else "saline"}
    return out


# ------------------------------------------------------------------ feature extraction
def weather_features(weather: dict | None, crop: dict, today: date):
    if not weather:
        return None
    iso = today.isoformat()
    days = weather["days"]
    past = [d for d in days if d["date"] < iso]
    fut = [d for d in days if d["date"] >= iso]
    if len(past) < 5:
        return None
    p7, p14 = past[-7:], past[-14:]
    roll = [sum(d["rain"] for d in past[-10:][i:i + 3]) for i in range(max(1, len(past[-10:]) - 2))]
    return {
        "rain14": sum(d["rain"] for d in p14),
        "heavy3": max(roll) if roll else 0.0,
        "hot_days": sum(1 for d in p7 if d["tmax"] is not None and d["tmax"] >= crop["heat_c"]),
        "cold_days": sum(1 for d in past[-5:] if d["tmin"] is not None and d["tmin"] <= crop["cold_c"]),
        "humid_days": sum(1 for d in p7 if d["rh"] is not None and d["rh"] >= 80 and d["rain"] >= 1),
        "rain_next3": sum(d["rain"] for d in fut[:3]),
        "rain_next2": sum(d["rain"] for d in fut[:2]),
    }


def _ev(*items):
    return [i for i in items if i]


# ------------------------------------------------------------------ diagnosis
def diagnose(crop, ev, wf, soil, chk, day, stage):
    last = ev.get("last") or {}
    status = ev["status"]
    early = status == "normal" and bool(chk) and chk["issue_rate"] >= 0.15   # photos found a problem before the satellite did
    needed = status in ("watch", "abnormal") or early
    missing = []
    if not soil:
        missing.append({"key": "soil", "text": "Add your soil test values so nutrient causes can be checked."})
    if not chk:
        missing.append({"key": "checkup", "text": "Do a weekly photo checkup so pests and diseases can be ruled in or out."})
    elif chk.get("age_days", 0) > 10:
        missing.append({"key": "checkup", "text": "Your last photo checkup is more than 10 days old. Do a new one."})
    if wf is None:
        missing.append({"key": "weather", "text": "Weather history is not available for this farm yet."})

    if not needed:
        return {"needed": False, "early": False, "causes": [], "missing": missing, "confidence": "high" if soil and chk else "medium"}

    ndmi, ndre, ndvi = last.get("ndmi"), last.get("ndre"), last.get("ndvi")
    ratio = (ndre / ndvi) if (ndre is not None and ndvi) else None
    dev = ev["deviation_pct"] or 0.0
    early_devs = [r["dev_pct"] for r in ev["series"] if r["day"] <= 25]
    sensitive = stage["name"] in crop.get("sensitive", [])
    scores = []

    def add(key, title, score, evidence, actions):
        scores.append({"key": key, "title": title, "score": int(max(0, min(100, score))), "evidence": evidence, "actions": actions})

    # water stress
    s, e = 0, []
    if wf and wf["rain14"] < 10:
        s += 40; e.append(f"Only {wf['rain14']:.0f} mm of rain in the last 14 days")
    if ndmi is not None and ndmi < 0.12:
        s += 35; e.append(f"Satellite moisture index is low ({ndmi:.2f})")
    if wf and wf["hot_days"] >= 2:
        s += 10; e.append(f"{wf['hot_days']} hot days in the last week")
    if sensitive and s:
        s += 5
    add("water", "Water stress", s, e, [
        "Check soil moisture 10 cm below the surface. If dry, irrigate within 1 to 2 days.",
        "Irrigate early morning or evening and mulch to hold moisture.",
        "Water the whole root zone slowly instead of frequent light watering."])

    # waterlogging or nutrient wash-out
    s, e = 0, []
    if wf and wf["heavy3"] >= 50:
        s += 40; e.append(f"Heavy rain of about {wf['heavy3']:.0f} mm in 3 days recently")
    if ndmi is not None and ndmi > 0.45:
        s += 30; e.append(f"Satellite moisture index is very high ({ndmi:.2f})")
    add("waterlog", "Waterlogging or nutrient wash-out", s, e, [
        "Open drain channels so water does not stand around roots.",
        "Wait for the field to drain before you walk in or work it.",
        "After the field dries, a nutrient top-up may be needed. Confirm with a soil test."])

    # nitrogen
    s, e = 0, []
    if ratio is not None and ratio < 0.45:
        s += 35; e.append("Leaf chlorophyll signal (red-edge) is low compared with overall greenness")
    if soil and soil.get("n", {}).get("rating") == "low":
        s += 40; e.append(f"Soil nitrogen is low ({soil['n']['value']:.0f} kg/ha)")
    if wf and wf["heavy3"] >= 50:
        s += 15; e.append("Heavy rain can wash nitrogen out of the soil")
    add("nitrogen", "Nitrogen shortage", s, e, [
        "Confirm with a soil test. If nitrogen is low, apply a top-dose as recommended by your Soil Health Card or agriculture officer.",
        "Do not apply right before heavy rain.",
        "Look for yellowing that starts on the older, lower leaves."])

    # heat
    s, e = 0, []
    if wf and wf["hot_days"] >= 3:
        s += 50; e.append(f"{wf['hot_days']} days above {crop['heat_c']}°C in the last week")
        if sensitive:
            s += 10; e.append("The crop is at a heat-sensitive stage")
    add("heat", "Heat stress", s, e, [
        "Irrigate lightly in the early morning or evening.", "Mulch and avoid spraying at midday."])

    # cold
    s, e = 0, []
    if wf and wf["cold_days"] >= 1:
        s += 55; e.append(f"{wf['cold_days']} cold night(s) at or below {crop['cold_c']}°C recently")
    add("cold", "Cold damage", s, e, ["Cover young plants at night where possible.", "Avoid heavy irrigation just before cold nights."])

    # pests and disease
    s, e = 0, []
    if chk:
        rate = chk["issue_rate"]
        if rate >= 0.30:
            s += 60
        elif rate >= 0.15:
            s += 45
        if rate >= 0.15:
            top = chk.get("top_issue")
            e.append(f"{rate*100:.0f}% of photographed spots show a problem" + (f", mostly {top}" if top else ""))
        if chk.get("spreading"):
            s += 15; e.append("The share of affected spots rose compared with last week")
    if wf and wf["humid_days"] >= 4:
        s += 25; e.append(f"{wf['humid_days']} humid, rainy days in the last week favour fungal disease")
    add("pest", "Pest or disease", s, e, [
        "Open the Checkup tab and photograph plants at the flagged spots.",
        "Remove badly affected plants and leaves where numbers are small.",
        "Ask your agriculture officer before spraying, and follow the product label."])

    # soil imbalance
    s, e = 0, []
    if soil:
        if soil.get("ph", {}).get("rating") in ("strongly acidic", "strongly alkaline"):
            s += 40; e.append(f"Soil pH is {soil['ph']['rating']} ({soil['ph']['value']})")
        if soil.get("p", {}).get("rating") == "low":
            s += 20; e.append("Soil phosphorus is low")
        if soil.get("k", {}).get("rating") == "low":
            s += 20; e.append("Soil potassium is low")
        if soil.get("ec", {}).get("rating") == "saline":
            s += 30; e.append("Soil salinity is high")
    add("soil", "Soil nutrient or pH imbalance", s, e, [
        "Follow your Soil Health Card advice for the crop.", "Ask your agriculture officer about soil correction for pH or salinity."])

    # sowing / timing
    s, e = 0, []
    if len(early_devs) >= 2 and sum(early_devs) / len(early_devs) < -15:
        s += 40; e.append("The crop was already behind the expected curve in its first weeks")
    add("timing", "Late sowing or slow start", s, e, [
        "Check the sowing date and variety against the local calendar.",
        "A slow start often catches up if water and nutrients are right."])

    causes = [c for c in scores if c["score"] >= 20 and (not early or c["key"] == "pest")]
    causes.sort(key=lambda c: -c["score"])
    for c in causes:
        c["level"] = "likely" if c["score"] >= 60 else "possible" if c["score"] >= 35 else "unlikely"
    sources = sum(1 for x in (soil, chk, wf) if x)
    confidence = "high" if sources == 3 else "medium" if sources == 2 else "low"
    return {"needed": True, "early": early, "causes": causes[:4], "missing": missing, "confidence": confidence,
            "unclear": not causes}


# ------------------------------------------------------------------ tips (normal growth)
def tips(crop, ev, wf, stage, soil, chk, alerts):
    out = [{"title": f"{stage['name']} stage", "text": stage["tip"], "kind": "stage"}]
    if wf and wf["rain_next2"] >= 20:
        out.append({"title": "Hold fertiliser and sprays", "text": f"About {wf['rain_next2']:.0f} mm of rain is due in 2 days. Wait until it passes so inputs are not washed away.", "kind": "weather"})
    if wf and wf["rain14"] < 15 and stage["name"] in crop.get("sensitive", []):
        out.append({"title": "Check soil moisture", "text": "It has been dry and the crop is at a sensitive stage. Irrigation now protects yield.", "kind": "weather"})
    if not soil:
        out.append({"title": "Add your soil test", "text": "With soil values the app can give fertiliser advice that fits your farm.", "kind": "data"})
    if not chk:
        out.append({"title": "Start your weekly photo checkup", "text": "Walking the field with the camera catches pests and disease before the satellite can see them.", "kind": "data"})
    if ev["status"] == "normal" and ev.get("health", 0) >= 90:
        out.append({"title": "Growth is strong", "text": "Keep your current irrigation and nutrition plan. Re-check after the next satellite pass.", "kind": "good"})
    return out[:5]
