from __future__ import annotations

import pathlib

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..services import DashboardServices
from ..urlstate import build_share_url

_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


def _svc(request: Request) -> DashboardServices:
    return request.app.state.services


@router.get("/insights", response_class=HTMLResponse)
def insights(request: Request) -> HTMLResponse:
    svc = _svc(request)
    movers = svc.get_weekly_rating_movers()
    accuracy = svc.get_model_accuracy_summary()
    # Render page
    return _templates.TemplateResponse(
        request,
        "insights.html",
        {
            "movers": movers,
            "accuracy": accuracy,
            "canonical_url": f"{str(request.base_url).rstrip('/')}{request.url.path}",
            "build_share_url": lambda **kwargs: build_share_url(services=svc, **kwargs),
        },
    )
