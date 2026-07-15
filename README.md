# Soccer Ratings Scraper

Small Python app that fetches:

- country rankings
- league lists inside each country
- team ratings for league `general`, `home`, and `away` pages
- team-vs-team comparison with implied 1X2 odds based on ratings
- team match-history parsing from the team page results table
- deduped league-wide history collection by iterating over every team in a league

Data comes from:

`https://www.soccer-rating.com/football-country-ranking/`

## Postgres

The project now includes a Postgres-ready schema in `soccer_ratings/schema.sql` and CLI commands that use `DATABASE_URL`.

For Supabase, use:

- `DIRECT_DATABASE_URL` for schema initialization and import jobs
- `DATABASE_URL` for pooled app/runtime access

Example `.env`:

```bash
DIRECT_DATABASE_URL="postgresql://postgres:YOUR_DB_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres?sslmode=require"
DATABASE_URL="postgresql://postgres.YOUR_PROJECT_REF:YOUR_DB_PASSWORD@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"
```

The CLI auto-loads `.env` from the project root.

Initialize the schema:

```bash
python3 app.py init-db
```

Import country rankings:

```bash
python3 app.py import-country-rankings
```

Import league ratings for one country:

```bash
python3 app.py import-league-ratings --country-url /England/
```

This now stores:

- country-level league summary rows
- team `general` snapshots
- team `home` snapshots
- team `away` snapshots

Import deduped league history:

```bash
python3 app.py import-league-history --league-url /England/UK1/
```

Import deduped history for every league in one country:

```bash
python3 app.py import-country-history --country-url /England/
```

Import deduped history for every ranked country and league:

```bash
python3 app.py import-all-history
```

## Deployment

Recommended production setup:

- Render for the web app
- Supabase for Postgres
- scheduled imports via Render Cron or GitHub Actions later

This repo now includes:

- `soccer_ratings/webapp.py` as the ASGI entrypoint
- `render.yaml` for Render deployment
- `/health` healthcheck endpoint

Render start command:

```bash
uvicorn soccer_ratings.webapp:app --host 0.0.0.0 --port $PORT
```

Required environment variables on Render:

```bash
DATABASE_URL=your_supabase_pooler_url
DIRECT_DATABASE_URL=your_supabase_direct_or_pooler_url
ADMIN_TOKEN=a_long_random_secret
```

## Security

The endpoints that scrape upstream or write to the database
(`/fragments/history-build`, `/fragments/history-import`,
`/fragments/country-import`, `/api/league-history/build`,
`/api/league-history/import`, `/api/country-history/import`) are
POST-only and require an admin token. Set `ADMIN_TOKEN` in the
environment (or `.env` locally); if it is unset these endpoints are
disabled, so a fresh deployment is closed by default.

Supply the token as an `X-Admin-Token` header, an `admin_token` query
parameter, or by logging in at `/admin` (see below). Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

The app also applies per-IP rate limits (120 requests/min in general,
5/min on the import/build endpoints), sends standard security headers
including a Content-Security-Policy, and serves a `robots.txt` that
keeps crawlers away from `/fragments/`, `/api/`, and `/admin`.

### `/admin`

Data import and cache-building tools ("Import Country to DB", "Build
Local Cache", "Import To DB") live on their own `/admin` page instead of
the public dashboard. `/admin` shows a token login form; on success it
sets an `httponly`, `secure`, `samesite=strict` session cookie (12h
`max_age`) so the admin buttons don't need the token resubmitted per
click — `require_admin` accepts this cookie as just another valid
credential source alongside the header/query/form token, so scripted
API callers are unaffected. "Log out" (`POST /admin/logout`) clears the
cookie. There's no separate admin account system — like `ADMIN_TOKEN`
itself, this is a single shared secret, appropriate for a one-operator
deployment.

Country-wide imports run as a background job instead of blocking the
request, since scraping every league in a large country can take minutes
— long enough to hit Render's request timeout. `POST
/fragments/country-import` and `POST /api/country-history/import` both
return immediately with a job snapshot; poll `GET
/fragments/import-job-status?job_id=...` (HTML) or `GET
/api/country-history/import/status?job_id=...` (JSON) for progress until
`status` is `done` or `error`. The dashboard UI does this polling for you
via HTMX. Job state is in-memory per process, so it resets on redeploy
and won't be visible across multiple instances if the app is ever scaled
beyond a single Render instance.

`DashboardServices` caches countries and leagues for 12 hours and
ratings for 6 hours (in-memory, per process — also reset on redeploy).
Every cache miss tries Postgres first and falls back to a live scrape of
soccer-rating.com if the query fails or returns nothing; a failed lookup
(e.g. a broken `DATABASE_URL`) logs a `WARNING` from the
`soccer_ratings.services` logger with the exception so it shows up in
Render's logs instead of failing silently.

After the first deploy, initialize and import data from a Render shell or another trusted environment:

```bash
python3 app.py init-db
python3 app.py import-country-rankings
python3 app.py import-league-ratings --country-url /England/
python3 app.py import-country-history --country-url /England/
```

## Scheduled data refresh

`.github/workflows/refresh-data.yml` runs nightly (03:00 UTC, plus a
manual "Run workflow" button) and:

1. `python3 app.py import-country-rankings` — refreshes the full country
   list. Cheap, always safe to run for everyone.
2. `python3 app.py refresh-known-history` — re-imports history only for
   countries that **already have at least one league in Postgres**
   (`db.list_countries_with_imported_leagues`, a DB-only query — it
   never crawls the source site just to figure out what to refresh).
   This means the nightly job automatically covers whatever you've
   imported via `/admin` or the CLI, with nothing to edit in the
   workflow file as you add more countries. It deliberately does **not**
   use `import-all-history`, which crawls every country in the world
   and would be a long, heavy, and rude crawl of soccer-rating.com to
   run nightly.

This runs on GitHub's infrastructure and connects to Supabase directly
(bypassing Render entirely), so it keeps working even during a Render
outage, and it's free on GitHub's standard runners.

**One-time setup:** add `DIRECT_DATABASE_URL` as a repository secret
(Settings → Secrets and variables → Actions → New repository secret),
using the same value as the one configured on Render. Without this
secret the workflow will fail at the first import step with a
"DIRECT_DATABASE_URL or DATABASE_URL is not set" error.

With this in place, the web app almost always serves warm data from
Postgres — the "Ratings updated Xh ago" freshness banner should
typically read under 24h — and first visitors after a Render redeploy
no longer pay the on-demand scrape cost.

## Shareable URLs

The dashboard reflects its selection in the address bar, so a country,
league, or a specific matchup can be bookmarked or shared as a link, e.g.
`/?country=/England/&league=/England/Premier-League/&home=Arsenal&away=Chelsea&margin=2`.
Opening a link like this renders the league (and comparison, if a
matchup is included) directly in the initial HTML response — no extra
round trip — which also gives each league a distinct `<title>` and meta
description for search engines.

Every dropdown/team change updates the URL via HTMX's `HX-Push-Url`
response header (see `soccer_ratings/urlstate.py` and the fragment
routes in `soccer_ratings/routes/fragments.py`), so back/forward
navigation and copy-pasting the current URL both work without any
client-side routing code.

## Ratings tables

Each league view shows a freshness banner ("Ratings updated 3h ago", via
`soccer_ratings/timeutil.py`'s `relative_time` Jinja filter) based on the
`rating_snapshots.fetched_at` timestamp from Postgres, or "Live data —
not yet cached" when ratings were scraped on the fly instead of loaded
from the database.

The Home/Away rating tables support client-side sorting (click a column
header) and a text filter box above them that narrows both tables by
team name at once — both are plain event-delegated JS in
`soccer_ratings/static/app.js`, so they keep working after HTMX swaps in
new league content without any re-initialization step. When a matchup
is selected in the Single Match tab, the two chosen teams are
highlighted in their respective tables.

## SEO

Every page sets a meta description, a canonical link, OpenGraph tags
(`og:type`/`site_name`/`title`/`description`/`url`), and a Twitter
summary card, all derived from the same title/description used for
`<title>` — see the `{% set page_title %}`/`page_description` block in
`templates/index.html`. Selecting a league changes all of these to
that league's name, so shared links preview correctly.

`GET /sitemap.xml` lists the homepage, one entry per country, and one
entry per league that has been imported into Postgres —
`DashboardServices.get_known_leagues_by_country()` deliberately never
falls back to a live scrape (unlike the normal league lookup), so a
crawler hitting the sitemap can't trigger scraping across every
not-yet-imported country. `robots.txt` points crawlers at it via a
`Sitemap:` line.

## Run

Fetch all countries:

```bash
python3 app.py countries
```

Fetch leagues for one country:

```bash
python3 app.py leagues --country-url /England/
```

Fetch one league's home ratings:

```bash
python3 app.py ratings --league-url /England/UK1/ --mode home
```

Fetch one league's away ratings:

```bash
python3 app.py ratings --league-url /England/UK1/ --mode away
```

Fetch historical matches for one team:

```bash
python3 app.py team-history --team-url /Borac-Banja-Luka/1234/
```

Fetch and dedupe historical matches for all teams in one league:

```bash
python3 app.py league-history --league-url /England/UK1/
```

Force refresh the cached league-history dataset:

```bash
python3 app.py league-history --league-url /England/UK1/ --refresh
```

Run the local dashboard:

```bash
python3 app.py dashboard
```

Then open `http://127.0.0.1:8001`.

Inside the dashboard you can:

- load home and away league ratings
- choose a home team and away team
- see implied `home / draw / away` probabilities and decimal odds
- switch to a `Multi Match` tab where rows are auto-created from the league size
- use each row to choose home and away teams and instantly see `1`, `X`, `2`, `Home DNB`, and `Away DNB`
- click `Export CSV` on the Multi Match tab to download the current rows (1X2/DNB/O-U/BTTS odds) as a `.csv` file, ready to paste into a spreadsheet — rows with no teams selected yet are skipped
- build and refresh a cached league-history dataset for the currently selected league

For larger imports, prefer the Postgres CLI commands over the dashboard button so you do not need to build history one league at a time.

Crawl all leagues in one country:

```bash
python3 app.py crawl-country --country-url /England/
```

Crawl all countries and all leagues:

```bash
python3 app.py crawl-all
```

Write any command output to a file:

```bash
python3 app.py crawl-country --country-url /England/ --output rankings.json
```

## Output

The app prints JSON. Example country output:

```json
[
  {
    "rank": 1,
    "country": "England",
    "rating": 2429.79,
    "country_path": "/England/"
  }
]
```

Example league output:

```json
[
  {
    "rank": 1,
    "league": "Premier League",
    "rating": 2313.46,
    "league_path": "/England/"
  }
]
```

## Odds Model

The dashboard comparison uses:

- the selected home team's `home` rating
- the selected away team's `away` rating
- an Elo-style logistic curve for the home/away win split
- a historical calibration layer from Postgres league matches when available
- a draw probability that is adjusted by nearby historical matches with similar rating gaps

So the current fair model is:

- live current ratings for the selected teams
- historical league matches from Postgres for the same competition
- expected draw tendency and goal expectation around the same rating-gap neighborhood

If no historical Postgres data is available for that league yet, the app falls back to the rating-only model.

When you enter a margin in the dashboard, the displayed odds are adjusted with the Shin method.

## Backtesting & market vs. model comparison

Every completed match already stored in Postgres for a league (`matches`,
populated by `import-league-history`/`import-country-history`) carries
both the ratings and the bookmaker's closing 1X2 odds as they were at the
time the match was played. The `Backtest` tab on a league page (and
`soccer_ratings/backtest.py`) replays that history:

- For each match, the plain ratings-only model (`calculate_match_probabilities`,
  no historical calibration) is compared against the market's de-vigged
  implied probabilities from the stored odds — deliberately skipping the
  history-calibrated model used elsewhere in the dashboard, since
  calibrating on the full league history and then backtesting against
  that same history would leak future results into each prediction.
- **Model accuracy**: average Brier score, pick accuracy (how often the
  model's most-likely outcome was correct), and a calibration table
  ("when the model said ~40%, how often did that actually happen?").
- **Market vs. model / value bets**: for each outcome where the model's
  probability exceeds the market's by more than a configurable edge
  threshold, a flat-stake bet is simulated against the actual result,
  rolled up into total staked/profit, hit rate, and ROI.

Adjust the edge threshold and stake inline on the tab (HTMX re-runs the
backtest without a full page reload) or via the API/CLI:

```bash
python3 app.py backtest --league-url /England/UK1/ --edge-threshold 5 --stake 1
```

```
GET /api/backtest?league_url=/England/UK1/&edge_threshold=5&stake=1
```

Leagues with no imported history yet show an empty state — run
`import-league-history`/`import-country-history` (or the `/admin` import
buttons) first.

## Tests

```bash
python3 -m unittest discover -s tests
```
