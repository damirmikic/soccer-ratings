from __future__ import annotations

import errno
import json
import pathlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .services import DashboardServices

_TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"
_STATIC_DIR = pathlib.Path(__file__).parent / "static"

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ef233c" />
      <stop offset="100%" stop-color="#0ea5e9" />
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="#0f172a" />
  <rect x="4" y="4" width="56" height="56" rx="13" fill="url(#bg)" />
  <circle cx="32" cy="32" r="16" fill="#ffffff" />
  <path d="M32 20l6 4-2 7h-8l-2-7 6-4zm-9 15h6l2 6-5 4-6-4 3-6zm18 0h6l3 6-6 4-5-4 2-6zm-9 9 5 4-2 6h-6l-2-6 5-4z" fill="#111827" />
</svg>
"""


class DashboardBindError(RuntimeError):
    """Raised when the dashboard cannot bind its requested address."""


# ---------------------------------------------------------------------------
# Legacy ThreadingHTTPServer handler (used by `python app.py dashboard`)
# ---------------------------------------------------------------------------

def create_dashboard_handler() -> type[BaseHTTPRequestHandler]:
    services = DashboardServices()
    index_html = (_TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)

            if parsed.path == "/":
                self._send_html(index_html)
                return

            if parsed.path == "/favicon.svg":
                self._send_svg(FAVICON_SVG)
                return

            if parsed.path == "/static/style.css":
                self._send_text(
                    (_STATIC_DIR / "style.css").read_text(encoding="utf-8"),
                    "text/css; charset=utf-8",
                )
                return

            if parsed.path == "/static/app.js":
                self._send_text(
                    (_STATIC_DIR / "app.js").read_text(encoding="utf-8"),
                    "application/javascript; charset=utf-8",
                )
                return

            if parsed.path == "/api/countries":
                self._send_json({"countries": services.get_countries()})
                return

            if parsed.path == "/api/leagues":
                params = parse_qs(parsed.query)
                country_url = _require_query_param(params, "country_url")
                if not country_url:
                    self._send_json(
                        {"error": "Missing required query parameter: country_url"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json({"leagues": services.get_leagues(country_url)})
                return

            if parsed.path == "/api/league-ratings":
                params = parse_qs(parsed.query)
                league_url = _require_query_param(params, "league_url")
                if not league_url:
                    self._send_json(
                        {"error": "Missing required query parameter: league_url"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                payload = dict(services.get_ratings(league_url))
                payload["league_stats"] = services.get_league_stats(league_url)
                self._send_json(payload)
                return

            if parsed.path == "/api/compare":
                params = parse_qs(parsed.query)
                league_url = _require_query_param(params, "league_url")
                home_team = _require_query_param(params, "home_team")
                away_team = _require_query_param(params, "away_team")
                margin_percent = _parse_float_query_param(params, "margin", default=0.0)
                if not league_url or not home_team or not away_team:
                    self._send_json(
                        {"error": "Missing required query parameters: league_url, home_team, away_team"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                try:
                    comparison = services.get_comparison(
                        league_url=league_url,
                        home_team=home_team,
                        away_team=away_team,
                        margin_percent=margin_percent,
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(comparison)
                return

            if parsed.path == "/api/league-history/status":
                params = parse_qs(parsed.query)
                league_url = _require_query_param(params, "league_url")
                if not league_url:
                    self._send_json(
                        {"error": "Missing required query parameter: league_url"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(services.get_history_status(league_url))
                return

            if parsed.path == "/api/league-history/build":
                params = parse_qs(parsed.query)
                league_url = _require_query_param(params, "league_url")
                refresh = _require_query_param(params, "refresh") == "1"
                if not league_url:
                    self._send_json(
                        {"error": "Missing required query parameter: league_url"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(services.build_history_cache(league_url, refresh))
                return

            if parsed.path == "/api/league-history/import":
                params = parse_qs(parsed.query)
                league_url = _require_query_param(params, "league_url")
                if not league_url:
                    self._send_json(
                        {"error": "Missing required query parameter: league_url"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                try:
                    payload = services.import_history_to_db(league_url)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._send_json(payload)
                return

            if parsed.path == "/api/country-history/import":
                params = parse_qs(parsed.query)
                country_url = _require_query_param(params, "country_url")
                if not country_url:
                    self._send_json(
                        {"error": "Missing required query parameter: country_url"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                try:
                    payload = services.import_country_to_db(country_url)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._send_json(payload)
                return

            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_text(body, "text/html; charset=utf-8", status)

        def _send_svg(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_text(body, "image/svg+xml; charset=utf-8", status)

        def _send_text(
            self,
            body: str,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return DashboardHandler


# ---------------------------------------------------------------------------
# FastAPI app (used by uvicorn / Render deployment)
# ---------------------------------------------------------------------------

def create_dashboard_app():
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles

    from .routes.compare import router as compare_router
    from .routes.countries import router as countries_router
    from .routes.history import router as history_router

    app = FastAPI(title="Soccer Ratings Dashboard")
    app.state.services = DashboardServices()

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(countries_router)
    app.include_router(compare_router)
    app.include_router(history_router)

    @app.get("/", response_class=Response)
    def index() -> Response:
        html = (_TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
        return Response(content=html, media_type="text/html")

    @app.get("/health", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

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
        probe_server = ThreadingHTTPServer((host, port), create_dashboard_handler())
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


# ---------------------------------------------------------------------------
# Helpers (used by legacy HTTP handler only)
# ---------------------------------------------------------------------------

def _require_query_param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _parse_float_query_param(
    params: dict[str, list[str]],
    name: str,
    default: float = 0.0,
) -> float:
    value = _require_query_param(params, name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default
