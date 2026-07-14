from __future__ import annotations

import errno
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi import Request

from .services import DashboardServices
from .timeutil import format_relative_time

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
_STATIC_DIR = pathlib.Path(__file__).parent / "static"

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
  <rect x="4" y="16" width="6" height="12" rx="1.5" fill="url(#fav-1)"/>
  <rect x="13" y="6" width="6" height="22" rx="1.5" fill="url(#fav-x)"/>
  <rect x="22" y="11" width="6" height="17" rx="1.5" fill="url(#fav-2)"/>
  <defs>
    <linearGradient id="fav-1" x1="4" y1="16" x2="10" y2="28" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#ef233c" />
      <stop offset="100%" stop-color="#d90429" />
    </linearGradient>
    <linearGradient id="fav-x" x1="13" y1="6" x2="19" y2="28" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#94a3b8" />
      <stop offset="100%" stop-color="#475569" />
    </linearGradient>
    <linearGradient id="fav-2" x1="22" y1="11" x2="28" y2="28" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0ea5e9" />
      <stop offset="100%" stop-color="#0284c7" />
    </linearGradient>
  </defs>
</svg>
"""


class DashboardBindError(RuntimeError):
    """Raised when the dashboard cannot bind its requested address."""


# ---------------------------------------------------------------------------
# FastAPI app (used by uvicorn / Render deployment)
# ---------------------------------------------------------------------------

ROBOTS_TXT = """User-agent: *
Disallow: /fragments/
Disallow: /api/
Disallow: /admin
"""


def create_dashboard_app():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    from .routes.admin import router as admin_router
    from .routes.compare import router as compare_router
    from .routes.countries import router as countries_router
    from .routes.fragments import router as fragments_router
    from .routes.history import router as history_router
    from .security import EXPENSIVE_PATHS, SECURITY_HEADERS, RateLimiter, client_ip

    app = FastAPI(
        title="ratings1x2",
        description="soccer match ratings",
    )
    app.state.services = DashboardServices()

    general_limiter = RateLimiter(limit=120, window_seconds=60)
    expensive_limiter = RateLimiter(limit=5, window_seconds=60)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        ip = client_ip(request)
        limiter = expensive_limiter if request.url.path in EXPENSIVE_PATHS else general_limiter
        if not limiter.allow(ip):
            response = JSONResponse(
                {"detail": "Too many requests, slow down."},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        else:
            response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["relative_time"] = format_relative_time

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(countries_router)
    app.include_router(compare_router)
    app.include_router(history_router)
    app.include_router(fragments_router)
    app.include_router(admin_router)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        svc: DashboardServices = app.state.services
        try:
            countries = svc.get_countries()
        except Exception:
            countries = []
        continents = sorted({c["continent"] for c in countries if c.get("continent")})

        # Optional shareable-link state: /?continent=...&country=...&league=...&home=...&away=...&margin=...
        selected_continent = request.query_params.get("continent", "")
        selected_country = request.query_params.get("country", "")
        selected_league = request.query_params.get("league", "")
        selected_home = request.query_params.get("home", "")
        selected_away = request.query_params.get("away", "")
        try:
            margin_percent = float(request.query_params.get("margin", "") or 0.0)
        except ValueError:
            margin_percent = 0.0

        visible_countries = countries
        if selected_continent:
            visible_countries = [c for c in countries if c.get("continent") == selected_continent]
        grouped: dict[str, list] = {}
        for c in visible_countries:
            grouped.setdefault(c.get("continent") or "Other", []).append(c)

        leagues: list[dict] = []
        selected_league_name = ""
        if selected_country:
            try:
                leagues = svc.get_leagues(selected_country)
            except Exception:
                leagues = []
            match = next((l for l in leagues if l.get("league_path") == selected_league), None)
            if match:
                selected_league_name = match.get("league") or ""

        league_context: dict = {}
        comparison = None
        if selected_league:
            try:
                ratings = svc.get_ratings(selected_league) or {}
                league_context = {
                    "league_url": selected_league,
                    "home": ratings.get("home", []),
                    "away": ratings.get("away", []),
                    "league_stats": svc.get_league_stats(selected_league),
                    "history_status": svc.get_history_status(selected_league),
                    "ratings_fetched_at": ratings.get("fetched_at"),
                    "ratings_source": ratings.get("source", "live"),
                }
                if selected_home and selected_away and selected_home != selected_away:
                    comparison = svc.get_comparison(
                        league_url=selected_league,
                        home_team=selected_home,
                        away_team=selected_away,
                        margin_percent=margin_percent,
                    )
            except Exception:
                league_context = {}
                comparison = None

        context = {
            "continents": continents,
            "grouped": grouped,
            "total_countries": len(countries),
            "selected_continent": selected_continent,
            "selected_country": selected_country,
            "selected_league": selected_league,
            "selected_league_name": selected_league_name,
            "selected_home": selected_home,
            "selected_away": selected_away,
            "margin_percent": margin_percent,
            "leagues": leagues,
            "country_url": selected_country,
            "d": comparison,
        }
        context.update(league_context)
        return templates.TemplateResponse(request, "index.html", context)

    @app.get("/health", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots() -> str:
        return ROBOTS_TXT

    @app.get("/favicon.svg")
    def favicon() -> Response:
        return Response(content=FAVICON_SVG, media_type="image/svg+xml")

    return app


# ---------------------------------------------------------------------------
# Local dev server entry point
# ---------------------------------------------------------------------------

def run_dashboard(host: str = "127.0.0.1", port: int = 8001) -> None:
    probe_server = None
    try:
        # Bind-only probe so a port conflict raises a friendly error before
        # uvicorn starts; the handler is never used to serve a request.
        probe_server = ThreadingHTTPServer((host, port), BaseHTTPRequestHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            next_port = port + 1
            raise DashboardBindError(
                "\n".join(
                    [
                        f"Dashboard address http://{host}:{port} is already in use.",
                        "Stop the existing process or choose another port:",
                        f"  python3 app.py dashboard --port {next_port}",
                        "To find the process on macOS:",
                        f"  lsof -nP -iTCP:{port} -sTCP:LISTEN",
                    ]
                )
            ) from exc
        raise
    finally:
        if probe_server is not None:
            probe_server.server_close()

    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn is required to run the deployment-ready dashboard. Install dependencies from requirements.txt."
        ) from exc

    app = create_dashboard_app()
    print(f"Dashboard running at http://{host}:{port}")
    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        pass
