"""Glue: builds the full picture of a farm and sends notifications."""
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import alerts as alerts_mod
from . import crops, diagnosis, push, satellite, weather
from .config import settings
from .db import dumps, loads, now_iso, one, q, run

IST = ZoneInfo("Asia/Kolkata")


def today_ist() -> date:
    return datetime.now(IST).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def farm_from_row(r: dict) -> dict:
    f = dict(r)
    f["geometry"] = loads(f.pop("geojson"))
    return f


def public_farm(f: dict) -> dict:
    return {k: f[k] for k in ("id", "name", "crop", "sowing_date", "geometry", "lat", "lng", "area_ha", "scenario", "reminder_day", "created_at")}


# ------------------------------------------------------------------ caches
def _age_hours(iso: str) -> float:
    try:
        t = datetime.fromisoformat(iso)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return 9999


def get_series(farm: dict, crop: dict, sowing: date, today: date, force=False):
    if satellite.mode() == "demo" or not settings.ee_enabled:
        src, obs, err = satellite.get_obs(farm, crop, sowing, today)
        return {"source": src, "obs": obs, "error": err}
    row = one("SELECT data, fetched_at FROM series_cache WHERE farm_id=?", (farm["id"],))
    if row and not force and _age_hours(row["fetched_at"]) < 12:
        d = loads(row["data"])
        if d and d.get("sowing") == farm["sowing_date"]:
            return {"source": d["source"], "obs": d["obs"], "error": None, "fetched_at": row["fetched_at"]}
    src, obs, err = satellite.get_obs(farm, crop, sowing, today)
    if src == "gee":
        run("INSERT OR REPLACE INTO series_cache(farm_id,data,fetched_at) VALUES(?,?,?)",
            (farm["id"], dumps({"source": src, "obs": obs, "sowing": farm["sowing_date"]}), now_iso()))
    return {"source": src, "obs": obs, "error": err}


def get_weather(farm: dict, today: date, force=False):
    row = one("SELECT data, fetched_at FROM weather_cache WHERE farm_id=?", (farm["id"],))
    if row and not force and _age_hours(row["fetched_at"]) < 3:
        d = loads(row["data"])
        if d and d["days"] and d["days"][-1]["date"] >= today.isoformat():
            return d, None
    w, warn = weather.get(farm, today)
    run("INSERT OR REPLACE INTO weather_cache(farm_id,data,fetched_at) VALUES(?,?,?)", (farm["id"], dumps(w), now_iso()))
    return w, warn


def get_soil(farm_id: int):
    row = one("SELECT data, updated_at FROM soil WHERE farm_id=?", (farm_id,))
    if not row:
        return None, None
    d = loads(row["data"], {})
    d["updated_at"] = row["updated_at"]
    return d, diagnosis.rate_soil(d)


# ------------------------------------------------------------------ checkups
def checkup_summary(photos: list, spots: list):
    analyzed = [p for p in photos if (p.get("result") or {}).get("status") in ("healthy", "issue")]
    issues = [p for p in analyzed if p["result"]["status"] == "issue"]
    unclear = [p for p in photos if (p.get("result") or {}).get("status") == "unclear"]
    errors = [p for p in photos if (p.get("result") or {}).get("status") == "error"]
    names = Counter(p["result"].get("issue") or "Unknown problem" for p in issues)
    rate = len(issues) / len(analyzed) if analyzed else 0.0
    return {
        "total_spots": len(spots), "photos": len(photos), "analyzed": len(analyzed),
        "healthy": len(analyzed) - len(issues), "issues": len(issues), "unclear": len(unclear), "errors": len(errors),
        "issue_rate": round(rate, 3),
        "top_issue": names.most_common(1)[0][0] if names else None,
        "by_issue": [{"name": n, "count": c} for n, c in names.most_common()],
        "hot_spots": [{"spot": p["spot_index"], "lat": p.get("lat"), "lng": p.get("lng"), "issue": p["result"].get("issue")} for p in issues],
    }


def load_session(sid: int):
    s = one("SELECT * FROM checkups WHERE id=?", (sid,))
    if not s:
        return None
    s["spots"] = loads(s["spots"], [])
    s["summary"] = loads(s["summary"])
    photos = q("SELECT id, spot_index, lat, lng, result, created_at FROM checkup_photos WHERE checkup_id=? ORDER BY spot_index", (sid,))
    for p in photos:
        p["result"] = loads(p["result"])
    s["photos"] = photos
    s["live"] = checkup_summary(photos, s["spots"])
    return s


def checkup_block(farm_id: int, today: date):
    rows = q("SELECT id FROM checkups WHERE farm_id=? ORDER BY id DESC LIMIT 12", (farm_id,))
    sessions = [load_session(r["id"]) for r in rows]
    active = next((s for s in sessions if s["status"] == "active"), None)
    done = [s for s in sessions if s["status"] == "done" and s["summary"]]
    last = None
    cand = [s for s in sessions if s["live"]["analyzed"] >= 10]
    if cand:
        s = cand[0]
        base = dict(s["summary"] or s["live"])
        base["week_start"] = s["week_start"]
        base["completed_at"] = s.get("completed_at")
        ref = s.get("completed_at") or s["created_at"]
        base["age_days"] = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(ref)).days) if ref else 0
        base["spreading"] = bool((s["summary"] or {}).get("spreading"))
        base["session_id"] = s["id"]
        last = base
    trend = [{"week": s["week_start"], "rate": s["summary"]["issue_rate"], "analyzed": s["summary"]["analyzed"]} for s in reversed(done)]
    return {
        "active": ({"id": active["id"], "target": active["target"], "photos": active["live"]["photos"], "week_start": active["week_start"]} if active else None),
        "last": last, "trend": trend,
        "this_week_done": any(s["week_start"] == week_start(today).isoformat() and s["status"] == "done" for s in sessions),
    }


# ------------------------------------------------------------------ overview
def build_overview(farm_row: dict, force=False):
    farm = farm_from_row(farm_row)
    crop = crops.get(farm["crop"])
    today = today_ist()
    sowing = date.fromisoformat(farm["sowing_date"])
    day = (today - sowing).days
    stage = crops.stage_for(crop, day)

    ser = get_series(farm, crop, sowing, today, force)
    ev = diagnosis.evaluate_series(crop, sowing, ser["obs"], today)
    w, w_warn = get_weather(farm, today, force)
    wf = diagnosis.weather_features(w, crop, today)
    w_alerts = alerts_mod.evaluate(w, crop, stage, today) if day >= 0 else []
    soil_raw, soil = get_soil(farm["id"])
    chk = checkup_block(farm["id"], today)
    diag = diagnosis.diagnose(crop, ev, wf, soil, chk["last"], day, stage)
    tips = diagnosis.tips(crop, ev, wf, stage, soil, chk["last"], w_alerts)

    curve = []
    for d in range(0, crop["duration"] + 1, 5):
        curve.append({"day": d, "date": (sowing + timedelta(days=d)).isoformat(), "expected": round(crops.expected_ndvi(crop, d), 3)})

    return {
        "today": today.isoformat(),
        "farm": public_farm(farm),
        "crop": {"key": farm["crop"], "name": crop["name"], "hi": crop["hi"], "mr": crop["mr"], "day": day,
                 "duration": crop["duration"], "progress": max(0.0, min(1.0, day / crop["duration"])),
                 "stage": {"name": stage["name"], "tip": stage["tip"], "index": stage["index"], "count": stage["count"]}},
        "satellite": {"source": ser["source"], "error": ser.get("error"), "status": ev["status"], "health": ev["health"],
                      "deviation_pct": ev["deviation_pct"], "message": ev["message"], "age_days": ev.get("age_days"),
                      "series": ev["series"], "last": ev["last"], "expected_curve": curve},
        "weather": {"source": w["source"], "warning": w_warn, "now": w["now"], "days": w["days"], "alerts": w_alerts},
        "soil": soil, "soil_raw": soil_raw, "diagnosis": diag, "tips": tips, "checkup": chk,
    }


# ------------------------------------------------------------------ notifications
def notify(user_id, farm_id, kind, level, title, body, dedupe, data=None, send_push=True) -> bool:
    try:
        run("INSERT INTO notifications(user_id,farm_id,kind,level,title,body,data,dedupe_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (user_id, farm_id, kind, level, title, body, dumps(data or {}), dedupe, now_iso()))
    except sqlite3.IntegrityError:
        return False
    if send_push and settings.push_enabled and level in ("warning", "urgent", "info"):
        push.send(user_id, title, body, "/")
    return True
