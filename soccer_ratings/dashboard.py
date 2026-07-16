from __future__ import annotations

from contextlib import asynccontextmanager
import errno
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi import Request

from .services import DashboardServices
from .sitemap import build_sitemap_xml
from .timeutil import format_relative_time
from .urlstate import build_share_url

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


@asynccontextmanager
async def lifespan(app):
    from .db import init_pool, close_pool
    init_pool()
    yield
    close_pool()


def create_dashboard_app():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates

    from .routes.admin import router as admin_router
    from .routes.backtest import router as backtest_router
    from .routes.compare import router as compare_router
    from .routes.countries import router as countries_router
    from .routes.fragments import router as fragments_router
    from .routes.history import router as history_router
    from .security import EXPENSIVE_PATHS, SECURITY_HEADERS, RateLimiter, client_ip

    app = FastAPI(
        title="ratings1x2",
        description="soccer match ratings",
        lifespan=lifespan,
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
    app.include_router(backtest_router)
    app.include_router(history_router)
    app.include_router(fragments_router)
    app.include_router(admin_router)

    def render_dashboard(
        request: Request,
        selected_continent: str = "",
        selected_country: str = "",
        selected_league: str = "",
        selected_home: str = "",
        selected_away: str = "",
        margin_percent: float = 0.0,
    ) -> HTMLResponse:
        svc: DashboardServices = app.state.services
        try:
            countries = svc.get_countries()
        except Exception:
            countries = []
        continents = sorted({c["continent"] for c in countries if c.get("continent")})

        if selected_country and not selected_continent:
            selected_continent = svc.get_continent_for_country(selected_country)

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
                    "backtest": svc.get_backtest(selected_league),
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

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        svc: DashboardServices = app.state.services
        # Legacy query parameters redirect to clean path URLs
        selected_country = request.query_params.get("country", "")
        if selected_country:
            selected_league = request.query_params.get("league", "")
            selected_home = request.query_params.get("home", "")
            selected_away = request.query_params.get("away", "")
            try:
                margin_percent = float(request.query_params.get("margin", "") or 0.0)
            except ValueError:
                margin_percent = 0.0

            from fastapi.responses import RedirectResponse
            clean_url = build_share_url(
                services=svc,
                country=selected_country,
                league=selected_league,
                home=selected_home,
                away=selected_away,
                margin=margin_percent,
            )
            return RedirectResponse(url=clean_url, status_code=301)

        selected_continent = request.query_params.get("continent", "")
        try:
            margin_percent = float(request.query_params.get("margin", "") or 0.0)
        except ValueError:
            margin_percent = 0.0

        return render_dashboard(
            request,
            selected_continent=selected_continent,
            margin_percent=margin_percent,
        )

    @app.get("/health", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots(request: Request) -> str:
        sitemap_url = str(request.base_url).rstrip("/") + "/sitemap.xml"
        return f"{ROBOTS_TXT}\nSitemap: {sitemap_url}\n"

    @app.get("/sitemap.xml")
    def sitemap(request: Request) -> Response:
        svc: DashboardServices = app.state.services
        base_url = str(request.base_url).rstrip("/")

        metadata = svc.get_sitemap_metadata() or {}
        homepage_lastmod = max(metadata.values()) if metadata else None

        entries = [
            {
                "loc": base_url + "/",
                "lastmod": homepage_lastmod,
                "changefreq": "daily",
                "priority": 1.0,
            }
        ]

        try:
            countries = svc.get_countries()
        except Exception:
            countries = []
        for country in countries:
            country_url = country.get("country_path")
            if country_url:
                url = base_url + build_share_url(services=svc, country=country_url)
                lastmod = metadata.get(country_url)
                entries.append({
                    "loc": url,
                    "lastmod": lastmod,
                    "changefreq": "weekly",
                    "priority": 0.8,
                })

        try:
            leagues_by_country = svc.get_known_leagues_by_country()
        except Exception:
            leagues_by_country = {}
        for country_url, leagues in leagues_by_country.items():
            for league in leagues:
                league_url = league.get("league_path")
                if league_url:
                    url = base_url + build_share_url(services=svc, country=country_url, league=league_url)
                    lastmod = metadata.get(league_url)
                    entries.append({
                        "loc": url,
                        "lastmod": lastmod,
                        "changefreq": "daily",
                        "priority": 0.6,
                    })

        return Response(content=build_sitemap_xml(entries), media_type="application/xml")


    @app.get("/favicon.svg")
    def favicon() -> Response:
        return Response(content=FAVICON_SVG, media_type="image/svg+xml")

    def check_partial_method_match(request: Request) -> None:
        from starlette.routing import Match
        ignore_endpoints = (country_page, league_page, matchup_page)
        for route in request.app.routes:
            if hasattr(route, "original_router"):
                for sub_route in route.original_router.routes:
                    if sub_route.endpoint in ignore_endpoints:
                        continue
                    try:
                        match, _ = sub_route.matches(request.scope)
                    except Exception:
                        match = Match.NONE
                    if match == Match.PARTIAL:
                        from fastapi import HTTPException
                        raise HTTPException(status_code=405, detail="Method Not Allowed")
            else:
                if not hasattr(route, "endpoint") or route.endpoint in ignore_endpoints:
                    continue
                try:
                    match, _ = route.matches(request.scope)
                except Exception:
                    match = Match.NONE
                if match == Match.PARTIAL:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=405, detail="Method Not Allowed")


    # Clean path routing wildcards defined last so they don't overshadow health/sitemap/robots/static
    @app.get("/{country_slug}", response_class=HTMLResponse)
    def country_page(request: Request, country_slug: str) -> HTMLResponse:
        check_partial_method_match(request)
        svc: DashboardServices = app.state.services
        from .slugify import get_country_path_by_slug
        country_path = get_country_path_by_slug(country_slug, svc)
        if not country_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Country not found")
        return render_dashboard(request, selected_country=country_path)

    @app.get("/{country_slug}/{league_slug}", response_class=HTMLResponse)
    def league_page(request: Request, country_slug: str, league_slug: str) -> HTMLResponse:
        check_partial_method_match(request)
        svc: DashboardServices = app.state.services
        from .slugify import get_country_path_by_slug, get_league_path_by_slug
        country_path = get_country_path_by_slug(country_slug, svc)
        if not country_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Country not found")
        league_path = get_league_path_by_slug(country_path, league_slug, svc)
        if not league_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="League not found")
        return render_dashboard(request, selected_country=country_path, selected_league=league_path)

    @app.get("/{country_slug}/{league_slug}/{matchup_slug}", response_class=HTMLResponse)
    def matchup_page(request: Request, country_slug: str, league_slug: str, matchup_slug: str) -> HTMLResponse:
        check_partial_method_match(request)
        svc: DashboardServices = app.state.services
        from .slugify import get_country_path_by_slug, get_league_path_by_slug, get_team_name_by_slug
        country_path = get_country_path_by_slug(country_slug, svc)
        if not country_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Country not found")
        league_path = get_league_path_by_slug(country_path, league_slug, svc)
        if not league_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="League not found")

        if "-vs-" not in matchup_slug:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Invalid matchup slug")

        parts = matchup_slug.split("-vs-")
        if len(parts) != 2:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Invalid matchup slug")

        home_slug, away_slug = parts
        home_team = get_team_name_by_slug(league_path, home_slug, svc)
        away_team = get_team_name_by_slug(league_path, away_slug, svc)
        if not home_team or not away_team:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Team not found")

        try:
            margin_percent = float(request.query_params.get("margin", "") or 0.0)
        except ValueError:
            margin_percent = 0.0

        return render_dashboard(
            request,
            selected_country=country_path,
            selected_league=league_path,
            selected_home=home_team,
            selected_away=away_team,
            margin_percent=margin_percent,
        )





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
