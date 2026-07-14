from __future__ import annotations

import hmac
import pathlib

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..security import (
    ADMIN_SESSION_COOKIE,
    configured_admin_token,
    is_admin_session_valid,
    require_admin,
)
from ..services import DashboardServices

_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix="/admin")

_SESSION_MAX_AGE_SECONDS = 12 * 3600


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("", response_class=HTMLResponse)
def admin_home(request: Request, error: str = Query("")) -> HTMLResponse:
    if not is_admin_session_valid(request):
        return _templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": bool(error), "disabled": not configured_admin_token()},
        )

    svc = _svc(request)
    countries = svc.get_countries()
    continents = sorted({c["continent"] for c in countries if c.get("continent")})
    grouped: dict[str, list] = {}
    for c in countries:
        grouped.setdefault(c.get("continent") or "Other", []).append(c)
    return _templates.TemplateResponse(
        request,
        "admin.html",
        {"continents": continents, "grouped": grouped},
    )


@router.post("/login")
async def admin_login(request: Request) -> RedirectResponse:
    configured = configured_admin_token()
    form = await request.form()
    supplied = str(form.get("admin_token", ""))

    if not configured or not supplied or not hmac.compare_digest(supplied, configured):
        return RedirectResponse(url="/admin?error=1", status_code=303)

    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        supplied,
        max_age=_SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response


@router.post("/logout")
def admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie(ADMIN_SESSION_COOKIE)
    return response


@router.get(
    "/league-panel",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin)],
)
def admin_league_panel(request: Request, league_url: str = Query(...)) -> HTMLResponse:
    svc = _svc(request)
    return _templates.TemplateResponse(
        request,
        "fragments/admin_league_panel.html",
        {
            "league_url": league_url,
            "history_status": svc.get_history_status(league_url),
        },
    )
