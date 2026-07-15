import json
import os
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from soccer_ratings.dashboard import create_dashboard_app
from soccer_ratings.jobs import JobManager


class StubServices:
    """Stands in for DashboardServices so tests never hit the network or DB."""

    def __init__(self) -> None:
        self._jobs = JobManager()

    def get_countries(self):
        return [{"country": "England", "country_path": "/England/", "continent": "Europe"}]

    def build_history_cache(self, league_url, refresh):
        return {
            "league_url": league_url,
            "team_count": 2,
            "raw_match_count": 10,
            "deduped_match_count": 5,
            "cache_path": "/tmp/cache.json",
        }

    def import_history_to_db(self, league_url):
        return {"league_url": league_url, "matches_imported": 5}

    def start_country_import_job(self, country_url):
        return self._jobs.create(kind="country_import", label=country_url)

    def run_country_import_job(self, job_id, country_url):
        self._jobs.run(
            job_id,
            lambda on_progress: {
                "country_url": country_url,
                "leagues_processed": 2,
                "matches_imported": 10,
                "failure_count": 0,
            },
        )

    def get_job(self, job_id):
        return self._jobs.get(job_id)

    def start_calibration_sweep_job(self):
        return self._jobs.create(kind="calibration_sweep", label="all imported leagues")

    def run_calibration_sweep_job(self, job_id):
        self._jobs.run(
            job_id,
            lambda on_progress: {
                "leagues_considered": 2,
                "leagues_evaluated": 1,
                "leagues_skipped": 1,
                "leagues": [
                    {
                        "league": "Premier League",
                        "league_path": "/England/Premier-League/",
                        "country": "England",
                        "matches_available": 50,
                        "min_matches_required": 30,
                        "best": {"weight_scale": 1.5, "avg_brier": 0.5, "matches_evaluated": 50},
                        "default_avg_brier": 0.6,
                        "results": [
                            {"weight_scale": 1.0, "avg_brier": 0.6, "matches_evaluated": 50},
                            {"weight_scale": 1.5, "avg_brier": 0.5, "matches_evaluated": 50},
                        ],
                    }
                ],
                "skipped_leagues": [
                    {
                        "league": "Tercera",
                        "league_path": "/Spain/Regional/",
                        "country": "Spain",
                        "matches_available": 5,
                        "min_matches_required": 30,
                        "best": None,
                    }
                ],
                "summary": {
                    "leagues_evaluated": 1,
                    "median_best_weight_scale": 1.5,
                    "avg_brier_improvement_vs_default": 0.1,
                },
            },
        )


def make_client() -> TestClient:
    app = create_dashboard_app()
    app.state.services = StubServices()
    return TestClient(app)


class AdminAuthTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": ""})
    def test_admin_endpoints_disabled_without_configured_token(self) -> None:
        client = make_client()
        response = client.post("/api/league-history/import?league_url=/x/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("ADMIN_TOKEN", response.json()["detail"])

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_admin_endpoints_reject_wrong_token(self) -> None:
        client = make_client()
        response = client.post(
            "/api/league-history/import?league_url=/x/",
            headers={"X-Admin-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_admin_endpoints_accept_header_token(self) -> None:
        client = make_client()
        response = client.post(
            "/api/league-history/import?league_url=/x/",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches_imported"], 5)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_fragment_endpoints_accept_form_token(self) -> None:
        client = make_client()
        response = client.post(
            "/fragments/history-import",
            data={"league_url": "/x/", "admin_token": "secret"},
        )
        self.assertEqual(response.status_code, 200)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_country_import_fragment_requires_token(self) -> None:
        client = make_client()
        response = client.post("/fragments/country-import", data={"country_url": "/England/"})
        self.assertEqual(response.status_code, 401)

    def test_import_endpoints_no_longer_accept_get(self) -> None:
        for path in (
            "/api/league-history/import?league_url=/x/",
            "/api/league-history/build?league_url=/x/",
            "/api/country-history/import?country_url=/x/",
            "/fragments/history-build?league_url=/x/",
            "/fragments/history-import?league_url=/x/",
            "/fragments/country-import?country_url=/x/",
            "/api/calibration-sweep",
            "/fragments/calibration-sweep",
        ):
            # Fresh app per request so the strict per-IP budget on these
            # endpoints doesn't turn later responses into 429s.
            response = make_client().get(path)
            self.assertEqual(response.status_code, 405, path)


class SecurityHeaderTests(unittest.TestCase):
    def test_security_headers_present(self) -> None:
        client = make_client()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_robots_txt_blocks_fragments_and_api(self) -> None:
        client = make_client()
        response = client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Disallow: /fragments/", response.text)
        self.assertIn("Disallow: /api/", response.text)


class RateLimitTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_expensive_endpoints_rate_limited(self) -> None:
        client = make_client()
        statuses = []
        for _ in range(6):
            response = client.post(
                "/api/league-history/build?league_url=/x/",
                headers={"X-Admin-Token": "secret"},
            )
            statuses.append(response.status_code)
        self.assertEqual(statuses[:5], [200] * 5)
        self.assertEqual(statuses[5], 429)

    def test_general_traffic_not_blocked_by_expensive_limit(self) -> None:
        client = make_client()
        for _ in range(10):
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)


class CountryImportBackgroundJobTests(unittest.TestCase):
    """Country import must never block the request — see services.py
    start_country_import_job / run_country_import_job and jobs.py."""

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_country_import_fragment_returns_immediately_and_completes_via_polling(self) -> None:
        client = make_client()
        response = client.post(
            "/fragments/country-import",
            data={"country_url": "/England/", "admin_token": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        job_id_match = re.search(r"job_id=([0-9a-f]{32})", response.text)
        self.assertIsNotNone(job_id_match, response.text)

        status_response = client.get(f"/fragments/import-job-status?job_id={job_id_match.group(1)}")
        self.assertEqual(status_response.status_code, 200)
        self.assertIn("Country import done: 2 leagues, 10 matches", status_response.text)

    def test_import_job_status_handles_unknown_job_id(self) -> None:
        client = make_client()
        response = client.get("/fragments/import-job-status?job_id=does-not-exist")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Import job not found", response.text)

    def test_import_job_status_shows_spinner_and_progress_bar_while_running(self) -> None:
        app = create_dashboard_app()
        svc = StubServices()
        app.state.services = svc
        client = TestClient(app)

        job_id = svc._jobs.create(kind="country_import", label="/England/")
        svc._jobs._update(job_id, current=1, total=3, message="Championship")

        response = client.get(f"/fragments/import-job-status?job_id={job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="spinner"', response.text)
        self.assertIn("Importing&hellip; 1/3 leagues", response.text)
        self.assertIn('class="progress-fill" style="width: 33.3%;"', response.text)
        # Still polling — the fragment must keep re-fetching itself.
        self.assertIn(f"/fragments/import-job-status?job_id={job_id}", response.text)

    def test_import_job_status_shows_indeterminate_bar_before_total_is_known(self) -> None:
        app = create_dashboard_app()
        svc = StubServices()
        app.state.services = svc
        client = TestClient(app)

        job_id = svc._jobs.create(kind="country_import", label="/England/")

        response = client.get(f"/fragments/import-job-status?job_id={job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Starting import&hellip;", response.text)
        self.assertIn("is-indeterminate", response.text)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_api_country_import_returns_202_with_job_payload(self) -> None:
        client = make_client()
        response = client.post(
            "/api/country-history/import?country_url=/England/",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["kind"], "country_import")

        status_response = client.get(f"/api/country-history/import/status?job_id={body['id']}")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "done")

    def test_api_country_import_status_404s_for_unknown_job(self) -> None:
        client = make_client()
        response = client.get("/api/country-history/import/status?job_id=nope")
        self.assertEqual(response.status_code, 404)


class CalibrationSweepBackgroundJobTests(unittest.TestCase):
    """Mirrors CountryImportBackgroundJobTests — the sweep must never
    block the request either, since it can take a while across many
    leagues. See services.py start_calibration_sweep_job /
    run_calibration_sweep_job."""

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_calibration_sweep_requires_token(self) -> None:
        client = make_client()
        response = client.post("/fragments/calibration-sweep")
        self.assertEqual(response.status_code, 401)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_calibration_sweep_fragment_returns_immediately_and_completes_via_polling(self) -> None:
        client = make_client()
        response = client.post(
            "/fragments/calibration-sweep",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        job_id_match = re.search(r"job_id=([0-9a-f]{32})", response.text)
        self.assertIsNotNone(job_id_match, response.text)

        status_response = client.get(f"/fragments/calibration-sweep-status?job_id={job_id_match.group(1)}")
        self.assertEqual(status_response.status_code, 200)
        self.assertIn("Swept 1 of 2 leagues", status_response.text)
        self.assertIn("Premier League", status_response.text)
        self.assertIn("Tercera", status_response.text)
        # "Copy Results" button and its embedded JSON payload for app.js to read.
        self.assertIn('id="calibration-sweep-copy"', status_response.text)
        self.assertIn('id="calibration-sweep-data"', status_response.text)
        payload = json.loads(
            status_response.text.split('id="calibration-sweep-data">', 1)[1].split("</script>", 1)[0]
        )
        self.assertEqual(payload["leagues_evaluated"], 1)
        self.assertEqual(payload["leagues"][0]["league"], "Premier League")

    def test_calibration_sweep_status_handles_unknown_job_id(self) -> None:
        client = make_client()
        response = client.get("/fragments/calibration-sweep-status?job_id=does-not-exist")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Calibration sweep job not found", response.text)

    def test_calibration_sweep_status_shows_spinner_and_progress_bar_while_running(self) -> None:
        app = create_dashboard_app()
        svc = StubServices()
        app.state.services = svc
        client = TestClient(app)

        job_id = svc._jobs.create(kind="calibration_sweep", label="all imported leagues")
        svc._jobs._update(job_id, current=2, total=4, message="La Liga")

        response = client.get(f"/fragments/calibration-sweep-status?job_id={job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="spinner"', response.text)
        self.assertIn("Sweeping&hellip; 2/4 leagues", response.text)
        self.assertIn('class="progress-fill" style="width: 50.0%;"', response.text)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_api_calibration_sweep_returns_202_with_job_payload(self) -> None:
        client = make_client()
        response = client.post(
            "/api/calibration-sweep",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["kind"], "calibration_sweep")

        status_response = client.get(f"/api/calibration-sweep/status?job_id={body['id']}")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "done")
        self.assertEqual(status_response.json()["result"]["leagues_evaluated"], 1)

    def test_api_calibration_sweep_status_404s_for_unknown_job(self) -> None:
        client = make_client()
        response = client.get("/api/calibration-sweep/status?job_id=nope")
        self.assertEqual(response.status_code, 404)


class DashboardServicesJobDedupTests(unittest.TestCase):
    """Verifies DashboardServices.start_country_import_job reuses an
    in-flight job instead of starting a second scrape of the same country."""

    def test_reuses_job_id_while_running(self) -> None:
        from soccer_ratings.services import DashboardServices

        svc = DashboardServices()
        first_job_id = svc.start_country_import_job("/England/")
        second_job_id = svc.start_country_import_job("/England/")
        self.assertEqual(first_job_id, second_job_id)

    def test_starts_new_job_once_previous_one_finished(self) -> None:
        from soccer_ratings.services import DashboardServices

        svc = DashboardServices()
        first_job_id = svc.start_country_import_job("/England/")
        svc._jobs.run(first_job_id, lambda on_progress: {"leagues_processed": 0})

        second_job_id = svc.start_country_import_job("/England/")
        self.assertNotEqual(first_job_id, second_job_id)


if __name__ == "__main__":
    unittest.main()
