from __future__ import annotations

from urllib.parse import urlencode

# Fixed order keeps generated URLs stable/diffable rather than depending
# on kwarg insertion order.
_PARAM_ORDER = ("continent", "country", "league", "home", "away", "margin")


def build_share_url(**params: str | float | None) -> str:
    """Build a shareable /?... URL from the non-empty state params.

    Drops empty strings and a zero margin so links stay as short as the
    state actually warrants (e.g. no country/league selected yet -> "/").
    """
    query: dict[str, str] = {}
    for key in _PARAM_ORDER:
        value = params.get(key)
        if value is None or value == "":
            continue
        if key == "margin":
            try:
                if float(value) == 0:
                    continue
            except (TypeError, ValueError):
                continue
        query[key] = value

    if not query:
        return "/"
    return "/?" + urlencode(query)
