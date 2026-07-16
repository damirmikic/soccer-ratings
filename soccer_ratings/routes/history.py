from __future__ import annotations

import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from ..security import require_admin
from ..services import DashboardServices

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


def _export_matches_response(
    request: Request,
    league_url: str,
    competition: str,
    format: str,
    completed_only: bool,
) -> Response:
    svc = _svc(request)
    slug = (league_url or competition or "all-matches").strip("/").replace("/", "-") or "all-matches"
    if format.lower() == "json":
        matches = svc.export_history_matches(league_url, competition, completed_only=completed_only)
        payload = json.dumps({"match_count": len(matches), "matches": matches}, indent=2, ensure_ascii=False)
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="history-{slug}.json"'},
        )
    csv_text = svc.export_history_csv(league_url, competition, completed_only=completed_only)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="history-{slug}.csv"'},
    )


@router.get("/api/league-history/status")
def league_history_status(request: Request, league_url: str = Query(...)) -> JSONResponse:
    return JSONResponse(_svc(request).get_history_status(league_url))


@router.get("/api/history/export")
def history_export(
    request: Request,
    league_url: str = Query(""),
    competition: str = Query(""),
    format: str = Query("csv"),
    completed_only: int = Query(1),
) -> Response:
    return _export_matches_response(request, league_url, competition, format, bool(completed_only))


@router.get("/api/league-history/export")
def league_history_export(
    request: Request,
    league_url: str = Query(""),
    competition: str = Query(""),
    format: str = Query("csv"),
    completed_only: int = Query(1),
) -> Response:
    return _export_matches_response(request, league_url, competition, format, bool(completed_only))


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
def country_history_import(
    request: Request,
    background_tasks: BackgroundTasks,
    country_url: str = Query(...),
) -> JSONResponse:
    """Starts an async job instead of blocking, since a large country's
    import can take minutes — long enough to hit Render's request timeout."""
    svc = _svc(request)
    job_id = svc.start_country_import_job(country_url)
    background_tasks.add_task(svc.run_country_import_job, job_id, country_url)
    return JSONResponse(svc.get_job(job_id), status_code=202)


@router.get("/api/country-history/import/status")
def country_history_import_status(request: Request, job_id: str = Query(...)) -> JSONResponse:
    job = _svc(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(job)


@router.post("/api/calibration-sweep", dependencies=[Depends(require_admin)])
def calibration_sweep(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Starts an async job — sweeping every imported league can take a
    while, long enough to hit Render's request timeout."""
    svc = _svc(request)
    job_id = svc.start_calibration_sweep_job()
    background_tasks.add_task(svc.run_calibration_sweep_job, job_id)
    return JSONResponse(svc.get_job(job_id), status_code=202)


@router.get("/api/calibration-sweep/status")
def calibration_sweep_status(request: Request, job_id: str = Query(...)) -> JSONResponse:
    job = _svc(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id")
    return JSONResponse(job)
