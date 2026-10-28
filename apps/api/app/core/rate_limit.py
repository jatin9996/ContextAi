import time
from collections import defaultdict

from app.core.errors import AppError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, *, limit: int, window_seconds: float) -> None:
        now = time.monotonic()
        recent = [stamp for stamp in self._hits[key] if now - stamp < window_seconds]
        if len(recent) >= limit:
            self._hits[key] = recent
            raise AppError("rate_limited", "Too many requests. Wait a moment and try again.", 429)
        recent.append(now)
        self._hits[key] = recent


limiter = RateLimiter()
