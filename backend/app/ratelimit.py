"""Tiny in-memory limiter so one user cannot run up the AI bill."""
import threading
import time
from collections import defaultdict, deque

_hits = defaultdict(deque)
_lock = threading.Lock()


def allow(key: str, limit: int, window: float = 60.0) -> bool:
    now = time.monotonic()
    with _lock:
        d = _hits[key]
        while d and now - d[0] > window:
            d.popleft()
        if len(d) >= limit:
            return False
        d.append(now)
        return True
