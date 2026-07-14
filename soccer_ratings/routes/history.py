from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..security import require_admin
from ..services import DashboardServices

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("/api/league-history/status")
def league_history_status(request: Request, league_url: str = Query(...)) -> JSONResponse:
    return JSONResponse(_svc(request).get_history_status(league_url))


@router.post("/api/league-history/build", dependencies=[Depends(require_admin)])
def league_history_build(
    request: Request,
    league_url: str = Query(...),
    refresh: int = Query(0),
) -> JSONResponse:
    return JSONResponse(_svc(request).build_history_cache(league_url, bool(refresh)))


@router.post("/api/league-history/import", dependencies=[Depends(require_admin)])
def league_history_import(request: Request, league_url: str = Query(...)) -> JSONResponse:
    try:
        payload = _svc(request).import_history_to_db(league_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(payload)


@router.post("/api/country-history/import", dependencies=[Depends(require_admin)])
def country_history_import(request: Request, country_url: str = Query(...)) -> JSONResponse:
    try:
        payload = _svc(request).import_country_to_db(country_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(payload)
