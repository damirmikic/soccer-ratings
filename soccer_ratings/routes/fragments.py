from __future__ import annotations

import pathlib

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..backtest import DEFAULT_EDGE_THRESHOLD_PERCENT
from ..odds import DEFAULT_MARKET_WEIGHT
from ..security import require_admin
from ..services import DashboardServices
from ..timeutil import format_relative_time
from ..urlstate import build_share_url

_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
_templates.env.filters["relative_time"] = format_relative_time

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
    response = _templates.TemplateResponse(
        request,
        "fragments/country_options.html",
        {"grouped": grouped},
    )
    # Country/league selection resets when the continent filter changes, so
    # the shareable URL only reflects the filter itself.
    response.headers["HX-Push-Url"] = build_share_url(services=_svc(request), continent=continent)
    return response


@router.get("/league-options", response_class=HTMLResponse)
def league_options(request: Request, country_url: str = Query(...)) -> HTMLResponse:
    svc = _svc(request)
    leagues = svc.get_leagues(country_url)
    response = _templates.TemplateResponse(
        request,
        "fragments/league_options.html",
        {"leagues": leagues},
    )
    response.headers["HX-Push-Url"] = build_share_url(
        services=svc,
        continent=svc.get_continent_for_country(country_url),
        country=country_url,
    )
    return response


@router.get("/league-content", response_class=HTMLResponse)
def league_content(
    request: Request,
    league_url: str = Query(...),
    country_url: str = Query(""),
) -> HTMLResponse:
    svc = _svc(request)
    ratings = svc.get_ratings(league_url) or {}
    home = ratings.get("home", [])
    away = ratings.get("away", [])
    response = _templates.TemplateResponse(
        request,
        "fragments/league_content.html",
        {
            "league_url": league_url,
            "country_url": country_url,
            "home": home,
            "away": away,
            "league_stats": svc.get_league_stats(league_url),
            "history_status": svc.get_history_status(league_url),
            "backtest": svc.get_backtest(league_url),
            "ratings_fetched_at": ratings.get("fetched_at"),
            "ratings_source": ratings.get("source", "live"),
        },
    )
    response.headers["HX-Push-Url"] = build_share_url(
        services=svc,
        continent=svc.get_continent_for_country(country_url),
        country=country_url,
        league=league_url,
    )
    return response


@router.get("/compare", response_class=HTMLResponse)
def compare(
    request: Request,
    league_url: str = Query(...),
    country_url: str = Query(""),
    home_team: str = Query(""),
    away_team: str = Query(""),
    margin: float = Query(0.0),
) -> HTMLResponse:
    if not home_team or not away_team or home_team == away_team:
        return HTMLResponse("")
    svc = _svc(request)
    try:
        data = svc.get_comparison(
            league_url=league_url,
            home_team=home_team,
            away_team=away_team,
            margin_percent=margin,
        )
    except Exception:
        return HTMLResponse('<p class="market-meta">Could not calculate comparison — check team selection.</p>')
    response = _templates.TemplateResponse(
        request,
        "fragments/comparison.html",
        {"d": data},
    )
    response.headers["HX-Push-Url"] = build_share_url(
        services=svc,
        continent=svc.get_continent_for_country(country_url),
        country=country_url,
        league=league_url,
        home=home_team,
        away=away_team,
        margin=margin,
    )
    return response


@router.get("/backtest", response_class=HTMLResponse)
def backtest(
    request: Request,
    league_url: str = Query(...),
    edge_threshold: float = Query(DEFAULT_EDGE_THRESHOLD_PERCENT),
    stake: float = Query(1.0),
    market_weight: float = Query(DEFAULT_MARKET_WEIGHT),
) -> HTMLResponse:
    svc = _svc(request)
    try:
        data = svc.get_backtest(
            league_url=league_url,
            edge_threshold_percent=edge_threshold,
            stake=stake,
            market_weight=market_weight,
        )
    except Exception:
        return HTMLResponse('<p class="market-meta">Could not run the backtest — check league selection.</p>')
    return _templates.TemplateResponse(
        request,
        "fragments/backtest_result.html",
        {"b": data},
    )


@router.post("/history-build", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def history_build(request: Request) -> HTMLResponse:
    league_url = await _form_or_query(request, "league_url")
    refresh = await _form_or_query(request, "refresh", "1")
    try:
        status = _svc(request).build_history_cache(league_url, refresh == "1")
        try:
            if isinstance(status, dict):
                status["db_match_count"] = len(_svc(request).export_history_matches(league_url))
        except Exception:
            pass
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
        try:
            if isinstance(status, dict):
                status["db_match_count"] = len(_svc(request).export_history_matches(league_url))
        except Exception:
            pass
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


@router.post("/dedupe-history", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def dedupe_history(request: Request) -> HTMLResponse:
    try:
        result = _svc(request).dedupe_history()
        return _templates.TemplateResponse(
            request,
            "fragments/dedupe_history_result.html",
            {"result": result},
        )
    except Exception as exc:
        return _templates.TemplateResponse(
            request,
            "fragments/dedupe_history_result.html",
            {"error": str(exc)},
        )


@router.post("/country-import", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def country_import(request: Request, background_tasks: BackgroundTasks) -> HTMLResponse:
    country_url = await _form_or_query(request, "country_url")
    svc = _svc(request)
    job_id = svc.start_country_import_job(country_url)
    background_tasks.add_task(svc.run_country_import_job, job_id, country_url)
    return _templates.TemplateResponse(
        request,
        "fragments/import_job_status.html",
        {"job": svc.get_job(job_id)},
    )


@router.get("/import-job-status", response_class=HTMLResponse)
def import_job_status(request: Request, job_id: str = Query(...)) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "fragments/import_job_status.html",
        {"job": _svc(request).get_job(job_id)},
    )


@router.post("/calibration-sweep", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def calibration_sweep(request: Request, background_tasks: BackgroundTasks) -> HTMLResponse:
    svc = _svc(request)
    job_id = svc.start_calibration_sweep_job()
    background_tasks.add_task(svc.run_calibration_sweep_job, job_id)
    return _templates.TemplateResponse(
        request,
        "fragments/calibration_sweep_status.html",
        {"job": svc.get_job(job_id)},
    )


@router.get("/calibration-sweep-status", response_class=HTMLResponse)
def calibration_sweep_status(request: Request, job_id: str = Query(...)) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "fragments/calibration_sweep_status.html",
        {"job": _svc(request).get_job(job_id)},
    )
