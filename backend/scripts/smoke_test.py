"""Quick end-to-end check in demo mode:  python scripts/smoke_test.py"""
import io, os, sys, tempfile
from datetime import timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp()
for k in ("CLERK_PUBLISHABLE_KEY", "ANTHROPIC_API_KEY", "EE_PROJECT"):
    os.environ[k] = ""
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from PIL import Image

from app import services
from app.main import app

def photo(seed):
    im = Image.new("RGB", (640, 480), (30 + seed * 3 % 80, 120, 40))
    b = io.BytesIO(); im.save(b, "JPEG"); return b.getvalue()

with TestClient(app) as c:
    cfg = c.get("/api/config").json()
    print("config:", cfg["auth"], cfg["satellite"], "ai:", cfg["ai"], "crops:", len(cfg["crops"]))
    sow = (services.today_ist() - timedelta(days=52)).isoformat()
    poly = {"type": "Polygon", "coordinates": [[[75.0, 19.0], [75.004, 19.0], [75.004, 19.003], [75.0, 19.003], [75.0, 19.0]]]}
    farms = {}
    for sc in ("healthy", "nitrogen", "water", "disease"):
        r = c.post("/api/farms", json={"name": f"Farm {sc}", "crop": "soybean", "sowing_date": sow, "geometry": poly, "scenario": sc})
        assert r.status_code == 200, r.text
        farms[sc] = r.json()["id"]
        ov = c.get(f"/api/farms/{farms[sc]}/overview").json()
        sat, d = ov["satellite"], ov["diagnosis"]
        print(f"{sc:9s} area={ov['farm']['area_ha']:.1f}ha stage={ov['crop']['stage']['name']:12s} status={sat['status']:8s} health={sat['health']} dev={sat['deviation_pct']} "
              f"causes={[ (x['title'], x['score']) for x in d['causes']][:3]} alerts={[a['type']+':'+a['level'] for a in ov['weather']['alerts']]}")
    fid = farms["nitrogen"]
    assert c.put(f"/api/farms/{fid}/soil", json={"n": 210, "p": 14, "k": 180, "ph": 7.1, "oc": 0.4}).status_code == 200
    ov = c.get(f"/api/farms/{fid}/overview").json()
    print("with soil ->", [(x["title"], x["score"], x["level"]) for x in ov["diagnosis"]["causes"]])

    r = c.post(f"/api/farms/{fid}/detect", files={"image": ("leaf.jpg", photo(1), "image/jpeg")}); assert r.status_code == 200, r.text
    print("detect:", r.json()["result"]["status"], r.json()["result"].get("issue"), "demo:", r.json()["result"]["demo"])

    ses = c.post(f"/api/farms/{farms['disease']}/checkups", json={"spots": 32}).json()
    print("checkup spots:", len(ses["spots"]), "priority:", sum(1 for s in ses["spots"] if s["priority"]))
    sid = ses["id"]
    for i in range(1, 33):
        r = c.post(f"/api/checkups/{sid}/photos", data={"spot_index": i}, files={"image": ("p.jpg", photo(i * 7), "image/jpeg")})
        assert r.status_code == 200, r.text
    live = r.json()["live"]; print("live:", {k: live[k] for k in ("photos", "analyzed", "healthy", "issues", "issue_rate", "top_issue")})
    done = c.post(f"/api/checkups/{sid}/complete").json(); print("done:", done["status"], done["summary"]["spreading"])
    ov = c.get(f"/api/farms/{farms['disease']}/overview").json()
    print("disease farm after checkup:", [(x["title"], x["score"]) for x in ov["diagnosis"]["causes"]][:3], "last:", ov["checkup"]["last"]["issue_rate"])

    ph = c.get(f"/api/photo/checkup/{done['photos'][0]['id']}"); print("photo fetch:", ph.status_code, ph.headers["content-type"])
    chat = c.post("/api/chat", json={"farm_id": fid, "message": "Why is my crop weak?", "history": [], "language": "en"}).json(); print("chat:", chat["mode"], chat["reply"][:120], "...")
    print("jobs:", c.post("/api/dev/run-jobs").json())
    n = c.get("/api/notifications").json(); print("notifications:", n["unread"], [x["title"] for x in n["items"]][:4])
    print("push test:", c.post("/api/push/test").json())
    assert c.delete(f"/api/farms/{farms['healthy']}").status_code == 200
    print("ALL OK")
