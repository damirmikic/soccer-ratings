from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..services import DashboardServices

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("/api/backtest")
def backtest(
    request: Request,
    league_url: str = Query(...),
    edge_threshold: float = Query(5.0),
    stake: float = Query(1.0),
) -> JSONResponse:
    try:
        payload = _svc(request).get_backtest(
            league_url=league_url,
            edge_threshold_percent=edge_threshold,
            stake=stake,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(payload)
