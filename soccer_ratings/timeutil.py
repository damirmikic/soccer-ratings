from __future__ import annotations

from datetime import datetime, timezone


def format_relative_time(moment: datetime | None, *, now: datetime | None = None) -> str:
    """Human-friendly "X ago" string, e.g. for rating snapshot freshness."""
    if moment is None:
        return ""

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    delta_seconds = max(0.0, (reference - moment).total_seconds())

    if delta_seconds < 60:
        return "just now"
    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(delta_seconds // 3600)
    if hours < 24:
        return f"{hours}h ago"
    days = int(delta_seconds // 86400)
    if days < 7:
        return f"{days}d ago"
    weeks = int(days // 7)
    if weeks < 5:
        return f"{weeks}w ago"
    months = int(days // 30)
    if months < 12:
        return f"{months}mo ago"
    years = int(days // 365)
    return f"{years}y ago"
