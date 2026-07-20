from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, name: str, default_limit: int, default_window_seconds: int = 60) -> None:
    limit = _int_env(f"RATE_LIMIT_{name.upper()}_REQUESTS", default_limit)
    window = _int_env(f"RATE_LIMIT_{name.upper()}_WINDOW_SECONDS", default_window_seconds)
    if limit <= 0 or window <= 0:
        return

    now = time.monotonic()
    key = (name, client_ip(request))
    bucket = BUCKETS[key]
    while bucket and now - bucket[0] >= window:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Quá nhiều request, vui lòng thử lại sau.")
    bucket.append(now)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
