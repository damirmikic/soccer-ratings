from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..services import DashboardServices

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("/api/compare")
def compare(
    request: Request,
    league_url: str = Query(...),
    home_team: str = Query(...),
    away_team: str = Query(...),
    margin: float = Query(0.0),
) -> JSONResponse:
    try:
        payload = _svc(request).get_comparison(
            league_url=league_url,
            home_team=home_team,
            away_team=away_team,
            margin_percent=margin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(payload)
