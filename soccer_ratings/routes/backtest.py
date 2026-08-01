from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..backtest import DEFAULT_EDGE_THRESHOLD_PERCENT
from ..odds import DEFAULT_MARKET_WEIGHT
from ..services import DashboardServices

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("/api/backtest")
def backtest(
    request: Request,
    league_url: str = Query(...),
    edge_threshold: float = Query(DEFAULT_EDGE_THRESHOLD_PERCENT),
    stake: float = Query(1.0),
    market_weight: float = Query(DEFAULT_MARKET_WEIGHT),
) -> JSONResponse:
    try:
        payload = _svc(request).get_backtest(
            league_url=league_url,
            edge_threshold_percent=edge_threshold,
            stake=stake,
            market_weight=market_weight,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(payload)
