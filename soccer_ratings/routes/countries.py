from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..services import DashboardServices

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("/api/countries")
def countries(request: Request) -> JSONResponse:
    return JSONResponse({"countries": _svc(request).get_countries()})


@router.get("/api/leagues")
def leagues(request: Request, country_url: str = Query(...)) -> JSONResponse:
    return JSONResponse({"leagues": _svc(request).get_leagues(country_url)})


@router.get("/api/league-ratings")
def league_ratings(request: Request, league_url: str = Query(...)) -> JSONResponse:
    svc = _svc(request)
    payload = dict(svc.get_ratings(league_url))
    payload["league_stats"] = svc.get_league_stats(league_url)
    return JSONResponse(payload)
