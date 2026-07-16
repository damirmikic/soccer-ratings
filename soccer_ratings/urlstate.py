from __future__ import annotations

from urllib.parse import urlencode
from .slugify import slugify, get_league_slug

# Fixed order keeps generated URLs stable/diffable rather than depending
# on kwarg insertion order.
_PARAM_ORDER = ("continent", "country", "league", "home", "away", "margin")


def build_share_url(services=None, **params: str | float | None) -> str:
    """Build a shareable clean path URL or a /?... fallback from the state params.

    If 'country' is present, returns a clean path:
      - /{country_slug}
      - /{country_slug}/{league_slug}
      - /{country_slug}/{league_slug}/{home_slug}-vs-{away_slug}
    With optional ?margin=... query param.
    Otherwise, falls back to query parameter format /?continent=...
    """
    country = params.get("country")
    if country:
        country_slug = slugify(str(country))
        path = f"/{country_slug}"

        league = params.get("league")
        if league:
            if services:
                league_slug = get_league_slug(str(country), str(league), services)
            else:
                parts = [p for p in str(league).split("/") if p]
                league_slug = slugify(parts[-1]) if parts else slugify(str(league))
            path += f"/{league_slug}"

            home = params.get("home")
            away = params.get("away")
            if home and away:
                home_slug = slugify(str(home))
                away_slug = slugify(str(away))
                path += f"/{home_slug}-vs-{away_slug}"

        query: dict[str, str] = {}
        margin = params.get("margin")
        if margin is not None and margin != "":
            try:
                if float(margin) != 0:
                    query["margin"] = str(margin)
            except (TypeError, ValueError):
                pass
        if query:
            path += "?" + urlencode(query)
        return path

    query = {}
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

