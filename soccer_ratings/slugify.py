from __future__ import annotations
import re

def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    if not text:
        return ""
    text = text.lower()
    # Replace non-alphanumeric/non-space/non-hyphen characters
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    # Replace spaces/hyphens with a single hyphen
    text = re.sub(r'[\s-]+', '-', text)
    return text.strip("-")

def get_country_path_by_slug(country_slug: str, services) -> str | None:
    """Resolve a country slug back to its original country_path (e.g. 'england' -> '/England/')."""
    if not country_slug:
        return None
    countries = services.get_countries()
    for c in countries:
        path = c.get("country_path")
        if path and slugify(path) == country_slug:
            return path
        name = c.get("country")
        if name and slugify(name) == country_slug:
            return path
    return None

def get_league_path_by_slug(country_path: str, league_slug: str, services) -> str | None:
    """Resolve a league slug back to its original league_path (e.g. 'premier-league' -> '/England/UK1/')."""
    if not country_path or not league_slug:
        return None
    leagues = services.get_leagues(country_path)
    for l in leagues:
        path = l.get("league_path")
        if path and slugify(path.split("/")[-2]) == league_slug:
            return path
        name = l.get("league")
        if name and slugify(name) == league_slug:
            return path
    return None

def get_team_name_by_slug(league_path: str, team_slug: str, services) -> str | None:
    """Resolve a team slug back to its exact team name (e.g. 'manchester-city' -> 'Manchester City')."""
    if not league_path or not team_slug:
        return None
    ratings = services.get_ratings(league_path) or {}
    for group in ("home", "away"):
        for t in ratings.get(group, []):
            team_name = t.get("team")
            if team_name and slugify(team_name) == team_slug:
                return team_name
    return None

def get_league_slug(country_path: str, league_path: str, services) -> str:
    """Get a slug for a league path, using its name if available, otherwise falling back to path segment."""
    if not country_path or not league_path:
        return ""
    try:
        leagues = services.get_leagues(country_path)
        for l in leagues:
            if l.get("league_path") == league_path:
                name = l.get("league")
                if name:
                    return slugify(name)
    except Exception:
        pass
    parts = [p for p in league_path.split("/") if p]
    if parts:
        return slugify(parts[-1])
    return slugify(league_path)
