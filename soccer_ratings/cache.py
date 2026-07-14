from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Per-key cache with absolute expiry, backed by a plain dict.

    Not thread-safe beyond what the GIL already gives a dict; fine for a
    single-process deployment like this one.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            # pop() instead of del: sync routes run in a thread pool, so two
            # threads can both see the same expired entry.
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (time.monotonic() + self._ttl, value)
