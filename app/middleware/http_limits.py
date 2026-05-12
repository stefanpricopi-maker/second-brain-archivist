from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger(__name__)


def _parse_positive_int(raw: str | None, default: int) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        v = int(str(raw).strip(), 10)
        return v if v > 0 else default
    except ValueError:
        return default


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Limitare simplă în memorie per client (IP).
    RATE_LIMIT_ENABLED=false dezactivează. Limite separate GET vs POST.
    """

    def __init__(self, app, *, window_sec: float = 60.0):
        super().__init__(app)
        self._get_hits: dict[str, deque[float]] = defaultdict(deque)
        self._post_hits: dict[str, deque[float]] = defaultdict(deque)
        self.window = window_sec
        self.enabled = (os.getenv("RATE_LIMIT_ENABLED") or "true").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        self.max_get = _parse_positive_int(os.getenv("RATE_LIMIT_GET_PER_MINUTE"), 240)
        self.max_post = _parse_positive_int(os.getenv("RATE_LIMIT_POST_PER_MINUTE"), 45)
        global_cap = _parse_positive_int(os.getenv("RATE_LIMIT_PER_MINUTE"), 0)
        if global_cap > 0:
            self.max_get = min(self.max_get, global_cap)
            self.max_post = min(self.max_post, global_cap)

    def _prune(self, dq: deque[float], now: float) -> None:
        while dq and now - dq[0] > self.window:
            dq.popleft()

    def _allow(self, dq: deque[float], now: float, limit: int) -> bool:
        self._prune(dq, now)
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not self.enabled:
            return await call_next(request)
        path = request.url.path
        if path in ("/health", "/favicon.ico"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        key = f"{client}"
        now = time.monotonic()
        method = request.method.upper()
        bucket = self._post_hits if method != "GET" else self._get_hits
        limit = self.max_post if method != "GET" else self.max_get
        dq = bucket[key]

        if not self._allow(dq, now, limit):
            log.warning("rate_limit exceeded method=%s path=%s client=%s", method, path, key)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Slow down or try again later."},
                headers={"Retry-After": str(int(self.window))},
            )

        return await call_next(request)


class StaticCacheControlMiddleware(BaseHTTPMiddleware):
    """Cache scurt pentru fișiere statice (UI)."""

    def __init__(self, app, *, prefix: str = "/static", max_age: int = 3600):
        super().__init__(app)
        self.prefix = prefix
        self.max_age = max_age

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        if request.url.path.startswith(self.prefix) and response.status_code < 400:
            response.headers.setdefault("Cache-Control", f"public, max-age={self.max_age}")
        return response
