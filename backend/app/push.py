"""Web Push to the farmer's phone (works when the app is installed and permission is granted)."""
import json
import logging

from .config import settings
from .db import dumps, loads, q, run

log = logging.getLogger("push")


def send(user_id: str, title: str, body: str, url: str = "/") -> int:
    if not settings.push_enabled:
        return 0
    from pywebpush import WebPushException, webpush

    sent = 0
    for s in q("SELECT id, sub FROM push_subs WHERE user_id=?", (user_id,)):
        info = loads(s["sub"])
        try:
            webpush(
                subscription_info=info,
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=settings.vapid_private,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=3600,
            )
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):
                run("DELETE FROM push_subs WHERE id=?", (s["id"],))
            else:
                log.warning("push failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("push error: %s", exc)
    return sent
