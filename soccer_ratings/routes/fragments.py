from __future__ import annotations

import html
import pathlib

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..security import require_admin
from ..services import DashboardServices

_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/fragments")


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


async def _form_or_query(request: Request, name: str, default: str = "") -> str:
    """HTMX POST buttons send hx-vals/hx-include values as form fields,
    while curl-style callers may keep using the query string."""
    value = request.query_params.get(name, "")
    if not value:
        form = await request.form()
        value = str(form.get(name, ""))
    return value or default


@router.get("/country-options", response_class=HTMLResponse)
def country_options(request: Request, continent: str = Query("")) -> HTMLResponse:
    countries = _svc(request).get_countries()
    if continent:
        countries = [c for c in countries if c.get("continent") == continent]
    grouped: dict[str, list] = {}
    for c in countries:
        grouped.setdefault(c.get("continent") or "Other", []).append(c)
    return _templates.TemplateResponse(
        request,
        "fragments/country_options.html",
        {"grouped": grouped},
    )


@router.get("/league-options", response_class=HTMLResponse)
def league_options(request: Request, country_url: str = Query(...)) -> HTMLResponse:
    leagues = _svc(request).get_leagues(country_url)
    return _templates.TemplateResponse(
        request,
        "fragments/league_options.html",
        {"leagues": leagues},
    )


@router.get("/league-content", response_class=HTMLResponse)
def league_content(request: Request, league_url: str = Query(...)) -> HTMLResponse:
    svc = _svc(request)
    ratings = svc.get_ratings(league_url) or {}
    home = ratings.get("home", [])
    away = ratings.get("away", [])
    return _templates.TemplateResponse(
        request,
        "fragments/league_content.html",
        {
            "league_url": league_url,
            "home": home,
            "away": away,
            "league_stats": svc.get_league_stats(league_url),
            "history_status": svc.get_history_status(league_url),
        },
    )


@router.get("/compare", response_class=HTMLResponse)
def compare(
    request: Request,
    league_url: str = Query(...),
    home_team: str = Query(""),
    away_team: str = Query(""),
    margin: float = Query(0.0),
) -> HTMLResponse:
    if not home_team or not away_team or home_team == away_team:
        return HTMLResponse("")
    try:
        data = _svc(request).get_comparison(
            league_url=league_url,
            home_team=home_team,
            away_team=away_team,
            margin_percent=margin,
        )
    except Exception:
        return HTMLResponse('<p class="market-meta">Could not calculate comparison — check team selection.</p>')
    return _templates.TemplateResponse(
        request,
        "fragments/comparison.html",
        {"d": data},
    )


@router.post("/history-build", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def history_build(request: Request) -> HTMLResponse:
    league_url = await _form_or_query(request, "league_url")
    refresh = await _form_or_query(request, "refresh", "1")
    try:
        status = _svc(request).build_history_cache(league_url, refresh == "1")
        return _templates.TemplateResponse(
            request,
            "fragments/history_status.html",
            {"status": status},
        )
    except Exception as exc:
        return _templates.TemplateResponse(
            request,
            "fragments/history_status.html",
            {"error": str(exc)},
        )


@router.post("/history-import", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def history_import(request: Request) -> HTMLResponse:
    league_url = await _form_or_query(request, "league_url")
    try:
        status = _svc(request).import_history_to_db(league_url)
        return _templates.TemplateResponse(
            request,
            "fragments/history_status.html",
            {"status": status, "imported": True},
        )
    except Exception as exc:
        return _templates.TemplateResponse(
            request,
            "fragments/history_status.html",
            {"error": str(exc)},
        )


@router.post("/country-import", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def country_import(request: Request) -> HTMLResponse:
    country_url = await _form_or_query(request, "country_url")
    try:
        result = _svc(request).import_country_to_db(country_url)
        leagues = result.get("leagues_processed", 0)
        matches = result.get("matches_imported", 0)
        failures = result.get("failure_count", 0)
        fail_note = f" ({failures} league(s) failed)" if failures else ""
        msg = f"Country import done: {leagues} leagues, {matches} matches{fail_note}."
    except Exception as exc:
        msg = f"Import failed: {exc}"
    return HTMLResponse(f'<span class="history-cache-meta">{html.escape(msg)}</span>')
