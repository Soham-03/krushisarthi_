"""Daily background work: refresh data, raise alerts, send the weekly checkup reminder."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from . import services
from .db import q

log = logging.getLogger("jobs")
_sched = None


def run_daily(force_reminder: bool = False) -> dict:
    today = services.today_ist()
    wk = services.week_start(today).isoformat()
    made = 0
    farms = q("SELECT * FROM farms")
    for row in farms:
        try:
            ov = services.build_overview(row, force=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("farm %s skipped: %s", row["id"], exc)
            continue
        uid, fid, name = row["user_id"], row["id"], ov["farm"]["name"]

        for a in ov["weather"]["alerts"]:
            if a["level"] in ("warning", "urgent"):
                extra = " Do an extra photo checkup today." if a["type"] == "fungal" else ""
                made += services.notify(uid, fid, "weather", a["level"], f"{name}: {a['title']}",
                                        a["message"] + " " + a["actions"][0] + extra, f"{fid}:{a['type']}:{a['level']}:{today}",
                                        {"type": a["type"]})
        sat = ov["satellite"]
        if sat["status"] in ("watch", "abnormal"):
            top = ov["diagnosis"]["causes"][0]["title"] if ov["diagnosis"]["causes"] else "cause not clear yet"
            made += services.notify(uid, fid, "growth", "urgent" if sat["status"] == "abnormal" else "warning",
                                    f"{name}: growth is below normal", f"{sat['message']} Most likely: {top}.",
                                    f"{fid}:growth:{sat['status']}:{wk}", {"status": sat["status"]})
        if today.weekday() == row["reminder_day"] or force_reminder:
            if ov["crop"]["day"] >= 0 and not ov["checkup"]["this_week_done"]:
                made += services.notify(uid, fid, "checkup", "info", f"{name}: weekly plant checkup",
                                        "Walk the field and photograph plants at the marked spots. It takes about 20 minutes.",
                                        f"{fid}:checkup:{wk}", {})
    return {"farms": len(farms), "notifications": made}


def start():
    global _sched
    if _sched:
        return
    _sched = BackgroundScheduler(timezone="Asia/Kolkata")
    _sched.add_job(run_daily, "cron", hour=7, minute=0, id="daily", misfire_grace_time=3600)
    _sched.start()
