from __future__ import annotations

import hmac
import os
import time
from collections import deque

from fastapi import HTTPException, Request

ADMIN_TOKEN_ENV = "ADMIN_TOKEN"
ADMIN_SESSION_COOKIE = "admin_session"

# Endpoints that trigger scrapes or DB writes get a much stricter budget
# than ordinary page/fragment reads.
EXPENSIVE_PATHS = frozenset(
    {
        "/fragments/history-build",
        "/fragments/history-import",
        "/fragments/country-import",
        "/api/league-history/build",
        "/api/league-history/import",
        "/api/country-history/import",
    }
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    ),
}


def configured_admin_token() -> str:
    return os.environ.get(ADMIN_TOKEN_ENV, "").strip()


def is_admin_session_valid(request: Request) -> bool:
    """Checks only the /admin login cookie, for pages that need to branch
    between a login form and the real content rather than raise a 401."""
    configured = configured_admin_token()
    if not configured:
        return False
    supplied = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    return bool(supplied) and hmac.compare_digest(supplied, configured)


async def require_admin(request: Request) -> None:
    """Guard for endpoints that scrape upstream or write to the database.

    The token may arrive as an X-Admin-Token header, an admin_token query
    parameter, an admin_token form field (the JSON API), or the /admin
    session cookie set after logging in there (the admin page's buttons
    rely on this so they don't need to resubmit the token per click). When
    ADMIN_TOKEN is not configured the endpoints stay disabled so a fresh
    deployment is closed by default.
    """
    configured = configured_admin_token()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin actions are disabled. Set the ADMIN_TOKEN environment variable to enable imports.",
        )

    supplied = (
        request.headers.get("x-admin-token", "")
        or request.query_params.get("admin_token", "")
        or request.cookies.get(ADMIN_SESSION_COOKIE, "")
    )
    if not supplied and request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            supplied = str(form.get("admin_token", ""))

    if not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


class RateLimiter:
    """Sliding-window per-key limiter. Single-process, in-memory.

    Runs inside the (single-threaded) event loop, so no locking is needed
    as long as allow() never awaits.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:
            self._prune(cutoff)
        return True

    def _prune(self, cutoff: float) -> None:
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] < cutoff]
        for key in stale:
            del self._hits[key]


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
