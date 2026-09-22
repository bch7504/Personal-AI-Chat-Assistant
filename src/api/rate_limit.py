"""Small in-memory request limiter for the app's single-worker deployment."""

import asyncio
import time
from collections import defaultdict, deque

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.auth.security import decode_access_token
from src.config import get_settings


def _parse_limit(value: str) -> tuple[int, float]:
    try:
        count_text, period_text = value.strip().lower().split("/", 1)
        seconds = {"second": 1.0, "minute": 60.0, "hour": 3600.0}[period_text.rstrip("s")]
        count = int(count_text)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid rate limit {value!r}; expected e.g. '15/minute'") from exc
    if count < 1:
        raise ValueError("Rate limit count must be positive")
    return count, seconds


class RequestRateLimiter:
    def __init__(self) -> None:
        self.enabled = get_settings().rate_limit_enabled
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._hits.clear()

    @staticmethod
    def _key(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            try:
                return f"user:{decode_access_token(authorization.removeprefix('Bearer ').strip())}"
            except (jwt.PyJWTError, KeyError):
                pass
        host = request.client.host if request.client else "unknown"
        return f"ip:{host}"

    @staticmethod
    def _tier(request: Request) -> tuple[str, str] | None:
        settings = get_settings()
        path = request.url.path.rstrip("/")
        if request.method == "OPTIONS" or path == "/health" or not path.startswith("/api/v1"):
            return None
        if path in {"/api/v1/chat/resume", "/api/v1/chat/status"}:
            return None
        if path == "/api/v1/auth/register":
            return "register", settings.rate_limit_register
        if path in {"/api/v1/auth/login", "/api/v1/auth/google"}:
            return "auth", settings.rate_limit_auth
        if path == "/api/v1/chat" and request.method == "POST":
            return "chat", settings.rate_limit_chat
        if request.method in {"GET", "HEAD"}:
            return "read", settings.rate_limit_read
        return "crud", settings.rate_limit_crud

    async def check(self, request: Request) -> tuple[bool, int]:
        tier = self._tier(request)
        if not self.enabled or tier is None:
            return True, 0
        tier_name, configured_limit = tier
        maximum, window = _parse_limit(configured_limit)
        now = time.monotonic()
        bucket_key = (tier_name, self._key(request))
        async with self._lock:
            hits = self._hits[bucket_key]
            cutoff = now - window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= maximum:
                retry_after = max(1, int(window - (now - hits[0])))
                return False, retry_after
            hits.append(now)
        return True, 0


request_limiter = RequestRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        allowed, retry_after = await request_limiter.check(request)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
