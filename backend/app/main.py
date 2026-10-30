"""KrushiSarthi API + static app server."""
import io
import logging
import random
import shutil
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import assistant, crops, geo, jobs, llm, rag, ratelimit, satellite, services, tools, vision
from .auth import current_user
from .config import settings
from .db import dumps, init_db, loads, now_iso, one, q, run

logging.basicConfig(level=logging.INFO)
MAX_UPLOAD = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    jobs.start()
    yield


app = FastAPI(title="KrushiSarthi", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ helpers
def own_farm(user_id: str, farm_id: int) -> dict:
    row = one("SELECT * FROM farms WHERE id=? AND user_id=?", (farm_id, user_id))
    if not row:
        raise HTTPException(404, "Farm not found")
    return row


def own_session(user_id: str, sid: int) -> dict:
    row = one("SELECT * FROM checkups WHERE id=? AND user_id=?", (sid, user_id))
    if not row:
        raise HTTPException(404, "Checkup not found")
    return row


async def read_image(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(400, "The photo is empty")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is too large. Please use a photo under 15 MB")
    try:
        from PIL import Image

        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise HTTPException(400, "This file is not a valid photo")
    return data


# ------------------------------------------------------------------ public
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    return {
        "clerk_publishable_key": settings.clerk_publishable_key if settings.clerk_enabled else "",
        "auth": "clerk" if settings.clerk_enabled else "demo",
        "satellite": satellite.mode(),
        "satellite_error": satellite.last_error(),
        "ai": settings.ai_enabled,
        "assistant": settings.assistant_enabled,
        "assistant_provider": settings.llm_provider if settings.assistant_enabled else None,
        "kb": rag.stats(),
        "push": settings.push_enabled,
        "vapid_public_key": settings.vapid_public if settings.push_enabled else "",
        "crops": crops.public_list(),
        "env": settings.app_env,
    }


# ------------------------------------------------------------------ farms
class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    crop: str
    sowing_date: str
    geometry: dict
    scenario: str = "healthy"
    reminder_day: int = Field(default=6, ge=0, le=6)


class FarmPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    crop: Optional[str] = None
    sowing_date: Optional[str] = None
    scenario: Optional[str] = None
    reminder_day: Optional[int] = Field(default=None, ge=0, le=6)


def _validate_geometry(geom: dict):
    try:
        g = geom.get("geometry", geom)
        assert g["type"] == "Polygon"
        ring = g["coordinates"][0]
        assert len(ring) >= 4
        for x, y in ring:
            assert -180 <= x <= 180 and -90 <= y <= 90
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [ring]}
    except Exception:
        raise HTTPException(400, "Please draw the farm boundary as a polygon on the map")


def _validate_date(s: str):
    from datetime import date

    try:
        d = date.fromisoformat(s)
    except Exception:
        raise HTTPException(400, "Sowing date must look like 2026-07-15")
    if d < date(2000, 1, 1) or d > services.today_ist() + timedelta(days=120):
        raise HTTPException(400, "Sowing date is out of range")
    return d


@app.get("/api/farms")
def list_farms(user=Depends(current_user)):
    return [services.public_farm(services.farm_from_row(r)) for r in q("SELECT * FROM farms WHERE user_id=? ORDER BY id", (user,))]


@app.post("/api/farms")
def create_farm(body: FarmIn, user=Depends(current_user)):
    if body.crop not in crops.CROPS:
        raise HTTPException(400, "Unknown crop")
    _validate_date(body.sowing_date)
    geom = _validate_geometry(body.geometry)
    area = geo.area_ha(geom)
    if area < 0.01 or area > 2000:
        raise HTTPException(400, "Farm area looks wrong. Draw the boundary again (0.01 to 2000 hectares)")
    if len(q("SELECT id FROM farms WHERE user_id=?", (user,))) >= 20:
        raise HTTPException(400, "You can add up to 20 farms")
    lat, lng = geo.centroid(geom)
    scenario = body.scenario if body.scenario in ("healthy", "nitrogen", "water", "disease", "late") else "healthy"
    fid = run("INSERT INTO farms(user_id,name,crop,sowing_date,geojson,lat,lng,area_ha,scenario,reminder_day,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (user, body.name.strip(), body.crop, body.sowing_date, dumps(geom), lat, lng, area, scenario, body.reminder_day, now_iso()))
    return services.public_farm(services.farm_from_row(own_farm(user, fid)))


@app.patch("/api/farms/{farm_id}")
def patch_farm(farm_id: int, body: FarmPatch, user=Depends(current_user)):
    own_farm(user, farm_id)
    sets, args = [], []
    if body.name is not None:
        sets.append("name=?"); args.append(body.name.strip())
    if body.crop is not None:
        if body.crop not in crops.CROPS:
            raise HTTPException(400, "Unknown crop")
        sets.append("crop=?"); args.append(body.crop)
    if body.sowing_date is not None:
        _validate_date(body.sowing_date)
        sets.append("sowing_date=?"); args.append(body.sowing_date)
    if body.scenario in ("healthy", "nitrogen", "water", "disease", "late"):
        sets.append("scenario=?"); args.append(body.scenario)
    if body.reminder_day is not None:
        sets.append("reminder_day=?"); args.append(body.reminder_day)
    if sets:
        run(f"UPDATE farms SET {', '.join(sets)} WHERE id=?", (*args, farm_id))
        run("DELETE FROM series_cache WHERE farm_id=?", (farm_id,))
    return services.public_farm(services.farm_from_row(own_farm(user, farm_id)))


@app.delete("/api/farms/{farm_id}")
def delete_farm(farm_id: int, user=Depends(current_user)):
    own_farm(user, farm_id)
    for sid in [r["id"] for r in q("SELECT id FROM checkups WHERE farm_id=?", (farm_id,))]:
        run("DELETE FROM checkup_photos WHERE checkup_id=?", (sid,))
    for t in ("checkups", "soil", "series_cache", "weather_cache", "detections"):
        run(f"DELETE FROM {t} WHERE farm_id=?", (farm_id,))
    run("DELETE FROM notifications WHERE farm_id=? AND user_id=?", (farm_id, user))
    run("DELETE FROM farms WHERE id=?", (farm_id,))
    shutil.rmtree(settings.uploads_dir / f"farm_{farm_id}", ignore_errors=True)
    return {"ok": True}


@app.get("/api/farms/{farm_id}/overview")
def overview(farm_id: int, refresh: bool = False, user=Depends(current_user)):
    return services.build_overview(own_farm(user, farm_id), force=refresh)


# ------------------------------------------------------------------ soil
class SoilIn(BaseModel):
    n: Optional[float] = Field(default=None, ge=0, le=5000)
    p: Optional[float] = Field(default=None, ge=0, le=1000)
    k: Optional[float] = Field(default=None, ge=0, le=5000)
    ph: Optional[float] = Field(default=None, ge=2, le=12)
    oc: Optional[float] = Field(default=None, ge=0, le=20)
    ec: Optional[float] = Field(default=None, ge=0, le=50)


@app.put("/api/farms/{farm_id}/soil")
def save_soil(farm_id: int, body: SoilIn, user=Depends(current_user)):
    own_farm(user, farm_id)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "Enter at least one value")
    run("INSERT OR REPLACE INTO soil(farm_id,data,updated_at) VALUES(?,?,?)", (farm_id, dumps(data), now_iso()))
    return {"ok": True}


@app.delete("/api/farms/{farm_id}/soil")
def clear_soil(farm_id: int, user=Depends(current_user)):
    own_farm(user, farm_id)
    run("DELETE FROM soil WHERE farm_id=?", (farm_id,))
    return {"ok": True}


@app.post("/api/farms/{farm_id}/soil/extract")
async def soil_extract(farm_id: int, image: UploadFile = File(...), user=Depends(current_user)):
    own_farm(user, farm_id)
    data = await read_image(image)
    return vision.extract_soil(data)


# ------------------------------------------------------------------ leaf scan
def _save_photo(rel: str, data: bytes) -> str:
    p = settings.uploads_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


@app.post("/api/farms/{farm_id}/detect")
async def detect(farm_id: int, image: UploadFile = File(...), user=Depends(current_user)):
    farm = own_farm(user, farm_id)
    raw = await read_image(image)
    result = vision.analyze_leaf(raw, farm["crop"], farm["scenario"])
    prepared = vision.prepare(raw)
    did = run("INSERT INTO detections(farm_id,user_id,path,result,created_at) VALUES(?,?,?,?,?)", (farm_id, user, "", dumps(result), now_iso()))
    rel = _save_photo(f"farm_{farm_id}/scan/{did}.jpg", prepared)
    run("UPDATE detections SET path=? WHERE id=?", (rel, did))
    return {"id": did, "result": result}


@app.get("/api/farms/{farm_id}/detections")
def detections(farm_id: int, user=Depends(current_user)):
    own_farm(user, farm_id)
    rows = q("SELECT id, result, created_at FROM detections WHERE farm_id=? ORDER BY id DESC LIMIT 12", (farm_id,))
    return [{"id": r["id"], "result": loads(r["result"]), "created_at": r["created_at"]} for r in rows]


@app.get("/api/photo/{kind}/{pid}")
def photo(kind: str, pid: int, user=Depends(current_user)):
    if kind == "scan":
        row = one("SELECT path, user_id FROM detections WHERE id=?", (pid,))
    elif kind == "checkup":
        row = one("SELECT p.path AS path, c.user_id AS user_id FROM checkup_photos p JOIN checkups c ON c.id=p.checkup_id WHERE p.id=?", (pid,))
    else:
        raise HTTPException(404)
    if not row or row["user_id"] != user or not row["path"]:
        raise HTTPException(404, "Photo not found")
    path = settings.uploads_dir / row["path"]
    if not path.exists():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------------ weekly checkup
class CheckupIn(BaseModel):
    spots: int = Field(default=30, ge=30, le=40)


def _mark_priority(farm: dict, spots: list):
    geom = loads(farm["geojson"])
    points, source = [], None
    if satellite.mode() == "gee":
        points, source = satellite.low_ndvi_points(geom, 4), "satellite"
    elif farm["scenario"] != "healthy":
        rnd = random.Random(int(farm["id"]) * 17)
        c = rnd.choice(spots)
        points, source = [(c["lat"], c["lng"])], "demo"
    idx = set()
    for lat, lng in points:
        idx.update(geo.nearest_spots(spots, lat, lng, 4 if source == "demo" else 1))
    for s in spots:
        s["priority"] = s["i"] in idx
    return source if idx else None


@app.post("/api/farms/{farm_id}/checkups")
def start_checkup(farm_id: int, body: CheckupIn, user=Depends(current_user)):
    farm = own_farm(user, farm_id)
    today = services.today_ist()
    ws = services.week_start(today).isoformat()
    active = one("SELECT id FROM checkups WHERE farm_id=? AND status='active' ORDER BY id DESC LIMIT 1", (farm_id,))
    if active:
        return services.load_session(active["id"])
    spots = geo.generate_spots(loads(farm["geojson"]), body.spots, seed=farm_id * 1000 + today.toordinal())
    pri = _mark_priority(farm, spots)
    sid = run("INSERT INTO checkups(farm_id,user_id,week_start,target,spots,status,created_at) VALUES(?,?,?,?,?,?,?)",
              (farm_id, user, ws, body.spots, dumps(spots), "active", now_iso()))
    s = services.load_session(sid)
    s["priority_source"] = pri
    return s


@app.get("/api/farms/{farm_id}/checkups")
def list_checkups(farm_id: int, user=Depends(current_user)):
    own_farm(user, farm_id)
    rows = q("SELECT id FROM checkups WHERE farm_id=? ORDER BY id DESC LIMIT 12", (farm_id,))
    out = []
    for r in rows:
        s = services.load_session(r["id"])
        out.append({"id": s["id"], "week_start": s["week_start"], "status": s["status"], "target": s["target"],
                    "photos": s["live"]["photos"], "summary": s["summary"] or s["live"], "completed_at": s["completed_at"]})
    return out


@app.get("/api/checkups/{sid}")
def get_checkup(sid: int, user=Depends(current_user)):
    own_session(user, sid)
    return services.load_session(sid)


@app.post("/api/checkups/{sid}/photos")
async def upload_checkup_photo(sid: int, spot_index: int = Form(...), lat: Optional[float] = Form(None),
                               lng: Optional[float] = Form(None), image: UploadFile = File(...), user=Depends(current_user)):
    ses = own_session(user, sid)
    if ses["status"] != "active":
        raise HTTPException(400, "This checkup is already finished")
    spots = loads(ses["spots"], [])
    if not any(s["i"] == spot_index for s in spots):
        raise HTTPException(400, "Unknown spot number")
    farm = own_farm(user, ses["farm_id"])
    raw = await read_image(image)
    result = vision.analyze_leaf(raw, farm["crop"], farm["scenario"], triage=True)
    spot = next(s for s in spots if s["i"] == spot_index)
    rel = _save_photo(f"farm_{farm['id']}/chk_{sid}/spot_{spot_index}.jpg", vision.prepare(raw))
    run("INSERT OR REPLACE INTO checkup_photos(id,checkup_id,spot_index,path,lat,lng,result,created_at) "
        "VALUES((SELECT id FROM checkup_photos WHERE checkup_id=? AND spot_index=?),?,?,?,?,?,?,?)",
        (sid, spot_index, sid, spot_index, rel, lat if lat is not None else spot["lat"], lng if lng is not None else spot["lng"], dumps(result), now_iso()))
    return services.load_session(sid)


@app.post("/api/checkups/{sid}/complete")
def complete_checkup(sid: int, user=Depends(current_user)):
    ses = own_session(user, sid)
    live = services.load_session(sid)
    if live["live"]["photos"] < 1:
        raise HTTPException(400, "Add at least one photo before finishing")
    summ = dict(live["live"])
    prev = None
    for r in q("SELECT id FROM checkups WHERE farm_id=? AND status='done' AND id<? ORDER BY id DESC LIMIT 1", (ses["farm_id"], sid)):
        prev = (services.load_session(r["id"]) or {}).get("summary")
    summ["prev_rate"] = prev["issue_rate"] if prev else None
    summ["delta"] = round(summ["issue_rate"] - prev["issue_rate"], 3) if prev else None
    summ["spreading"] = bool(prev and summ["issue_rate"] >= 0.10 and summ["issue_rate"] - prev["issue_rate"] >= 0.10)
    run("UPDATE checkups SET status='done', summary=?, completed_at=? WHERE id=?", (dumps(summ), now_iso(), sid))
    farm = own_farm(user, ses["farm_id"])
    name = farm["name"]
    if summ["analyzed"] >= 5:
        if summ["spreading"]:
            services.notify(user, farm["id"], "checkup", "urgent", f"{name}: problem is spreading",
                            f"{summ['issue_rate']*100:.0f}% of spots show a problem, up from {summ['prev_rate']*100:.0f}% last week" + (f", mainly {summ['top_issue']}." if summ["top_issue"] else "."), f"chk:{sid}")
        elif summ["issue_rate"] >= 0.15:
            services.notify(user, farm["id"], "checkup", "warning", f"{name}: problem found in checkup",
                            f"{summ['issues']} of {summ['analyzed']} photos show a problem" + (f", mainly {summ['top_issue']}." if summ["top_issue"] else "."), f"chk:{sid}")
        else:
            services.notify(user, farm["id"], "checkup", "info", f"{name}: checkup looks healthy",
                            f"{summ['healthy']} of {summ['analyzed']} photos look healthy. Next checkup in a week.", f"chk:{sid}", send_push=False)
    return services.load_session(sid)


@app.delete("/api/checkups/{sid}")
def delete_checkup(sid: int, user=Depends(current_user)):
    ses = own_session(user, sid)
    run("DELETE FROM checkup_photos WHERE checkup_id=?", (sid,))
    run("DELETE FROM checkups WHERE id=?", (sid,))
    shutil.rmtree(settings.uploads_dir / f"farm_{ses['farm_id']}" / f"chk_{sid}", ignore_errors=True)
    return {"ok": True}


# ------------------------------------------------------------------ assistant
class ChatIn(BaseModel):
    farm_id: int
    message: str = Field(min_length=1, max_length=1500)
    history: list = []
    language: str = "en"


LLM_HTTP = {"rate_limit": 429, "not_configured": 503, "timeout": 504, "network": 502}


@app.post("/api/chat")
def chat(body: ChatIn, user=Depends(current_user)):
    farm = own_farm(user, body.farm_id)
    if not ratelimit.allow(f"chat:{user}", settings.chat_rate_per_minute):
        raise HTTPException(429, "You are sending messages too quickly. Please wait a minute and try again.")
    language = body.language if body.language in assistant.LANG else "en"
    if not settings.assistant_enabled:
        ov = services.build_overview(farm)
        text, mode = assistant.reply(ov, body.message, body.history, language)
        return {"reply": text, "mode": mode, "grounded": False, "sources": [], "tools": [], "notes": ["offline"]}
    ctx = tools.ToolContext(user, farm)
    try:
        return assistant.run_agent(ctx, body.message, body.history, language)
    except llm.LLMError as err:
        logging.getLogger("chat").warning("LLM error (%s): %s", err.kind, err.message)
        raise HTTPException(LLM_HTTP.get(err.kind, 502), llm.user_message(err))


@app.get("/api/kb/status")
def kb_status(user=Depends(current_user)):
    return rag.stats()


@app.get("/api/kb/documents")
def kb_documents(user=Depends(current_user)):
    return q("SELECT id, title, publisher, published, url, language, crops, source_type, added_at FROM kb_documents ORDER BY id DESC LIMIT 200")


# ------------------------------------------------------------------ notifications
@app.get("/api/notifications")
def notifications(user=Depends(current_user)):
    rows = q("SELECT id, farm_id, kind, level, title, body, read, created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 60", (user,))
    return {"items": rows, "unread": sum(1 for r in rows if not r["read"])}


@app.post("/api/notifications/read")
def mark_read(user=Depends(current_user)):
    run("UPDATE notifications SET read=1 WHERE user_id=?", (user,))
    return {"ok": True}


class SubIn(BaseModel):
    subscription: dict


@app.post("/api/push/subscribe")
def push_subscribe(body: SubIn, user=Depends(current_user)):
    ep = body.subscription.get("endpoint")
    if not ep:
        raise HTTPException(400, "Invalid subscription")
    run("INSERT OR REPLACE INTO push_subs(user_id,endpoint,sub,created_at) VALUES(?,?,?,?)", (user, ep, dumps(body.subscription), now_iso()))
    return {"ok": True}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: SubIn, user=Depends(current_user)):
    run("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (body.subscription.get("endpoint"), user))
    return {"ok": True}


@app.post("/api/push/test")
def push_test(user=Depends(current_user)):
    services.notify(user, None, "test", "info", "Test notification", "Notifications are working on this phone.", f"test:{now_iso()}", send_push=False)
    from . import push

    sent = push.send(user, "KrushiSarthi", "Notifications are working on this phone.")
    return {"sent": sent, "push_enabled": settings.push_enabled}


# ------------------------------------------------------------------ jobs
@app.post("/api/dev/run-jobs")
def dev_run_jobs(user=Depends(current_user)):
    if settings.app_env == "production":
        raise HTTPException(403, "Disabled in production")
    return jobs.run_daily(force_reminder=True)


@app.get("/api/cron/run")
def cron_run(key: str = Query(...)):
    if not settings.cron_secret or key != settings.cron_secret:
        raise HTTPException(403, "Bad key")
    return jobs.run_daily()


# ------------------------------------------------------------------ app files
if (settings.static_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
