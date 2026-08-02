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
Countries and ratings each try Postgres first and fall back to a live
scrape of soccer-rating.com if the query fails or returns nothing. The
**league list is the other way around** — always live-scraped first, DB
only as a fallback if the scrape itself fails — so a country with only
one or two leagues imported still shows every league that actually
exists on the source site, not just the imported subset; the League
dropdown (on the dashboard and on `/admin`) is meant for discovering and
picking what to import next, not a view of import state. A failed
lookup (e.g. a broken `DATABASE_URL`, or soccer-rating.com erroring)
logs a `WARNING` from the `soccer_ratings.services` logger with the
exception so it shows up in Render's logs instead of failing silently.

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

Selecting a matchup on the Single Match tab also surfaces two panels
below the odds, both built from `soccer_ratings/matchhistory.py` and the
same `historical_matches` already loaded for that league — no extra
query or scrape:

- **Form guide**: each team's last 5 completed matches (any opponent),
  shown as a W/D/L strip with goals for/against and a record summary.
- **Head-to-head**: up to the last 10 previous meetings between the two
  selected teams (either venue), with the score and the bookmaker odds
  recorded at the time, alongside the current market odds for comparison.

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
- **Market-anchored calibration**: the raw model is blended toward the
  de-vigged market (`blend_with_market` in `soccer_ratings/odds.py`,
  `--market-weight`/`market_weight`, default 0.7 — i.e. 70% market/30%
  model) before anything else is computed from it. The market is close to
  well-calibrated on its own, so this blend corrects the model's
  systematic biases and confidence errors while still letting the ratings
  contribute whatever independent signal they have. The raw (unblended)
  model is still reported separately for comparison.
- **Model accuracy**: average Brier score for the blended model, the raw
  model, and the market itself (so the market is scored as an explicit
  baseline, not just implied by the edge numbers), pick accuracy (how
  often the blended model's most-likely outcome was correct), and a
  calibration table ("when the model said ~40%, how often did that
  actually happen?") built from the blended probabilities.
- **Market vs. model / value bets**: for each outcome where the blended
  model's probability exceeds a threshold, a flat-stake bet is simulated
  against the actual result, rolled up into total staked/profit, hit
  rate, and ROI. The edge is *relative* — `model_p / raw_implied_p - 1`
  — and priced against the raw, vigged odds actually on offer (not the
  de-vigged market probability), since the vig is money you'd really pay
  and a flat percentage-point gap means very different things at a 10%
  price versus a 70% one. The default threshold (`DEFAULT_EDGE_THRESHOLD_PERCENT`
  in `soccer_ratings/backtest.py`, currently 10%) reflects that relative
  scale, not the old absolute-percentage-point one.
- **Value bets by side, and an ROI trustworthiness check**: value bets
  are broken down per outcome (home/draw/away) with their own hit
  rate/staked/profit/ROI, because a book that's ~all bets on one side is
  a sign the "edge" is a systematic model bias rather than real per-match
  mispricing. `roi_trustworthy` is only true when bets are reasonably
  balanced across sides (no side above `MAX_TRUSTWORTHY_SIDE_SHARE`, 60%,
  of all value bets) *and* the blended model's Brier score beats the
  market's (`beats_market`) — `roi_caveats` explains which check(s)
  failed when it's false.

Adjust the edge threshold, stake, and market weight inline on the tab
(HTMX re-runs the backtest without a full page reload) or via the API/CLI:

```bash
python3 app.py backtest --league-url /England/UK1/ --edge-threshold 10 --stake 1 --market-weight 0.7
```

```
GET /api/backtest?league_url=/England/UK1/&edge_threshold=10&stake=1&market_weight=0.7
```

Leagues with no imported history yet show an empty state — run
`import-league-history`/`import-country-history` (or the `/admin` import
buttons) first.

## Tuning the history-calibration weight

`calibrate_probabilities_with_history` in `soccer_ratings/odds.py` blends
the ratings-only draw/win-share split with a league's actual history, but
how much it trusts that history (draw-rate weight capped at 0.4,
win-share weight capped at 0.28, both ramping in over ~24 effective
samples) was originally hand-picked, not fitted from data.

`soccer_ratings/tuning.py` lets you check that empirically. It walk-forward
backtests a league — predicting each match using *only* the matches
strictly before it, so nothing leaks from the future — at several
candidate `weight_scale` values (a multiplier on those weights: `0.0` is
the ratings-only model with history ignored entirely, `1.0` is the
current default, `2.0` trusts history twice as much) and reports which
minimizes average Brier score:

```bash
python3 app.py tune-calibration --league-url /England/UK1/
python3 app.py tune-calibration --league-url /England/UK1/ --weight-scales 0 0.5 1 1.5 2 --min-matches 50
```

Leagues below `--min-matches` (default 30) completed matches are skipped
outright — there's not enough signal to distinguish a genuinely better
weight from noise. This is an offline research tool: it reports what
would have minimized Brier score, it doesn't change the live app's
behavior — if a sweep says a different `weight_scale` consistently wins
across leagues, that's a signal to update the default in
`calibrate_probabilities_with_history`, not something applied
automatically.

### Running the sweep across every imported league at once

The `/admin` page has a **Model Tuning** section with a **"Run Calibration
Sweep (All Leagues)"** button. It runs `tune-calibration`'s sweep against
every league that has been imported into Postgres (DB-only discovery, the
same `leagues` table `refresh-known-history` uses — no live scrape), as a
background job so it doesn't block the request or hit Render's timeout on
a large database. The result summarizes:

- each league's best-performing `weight_scale` and how much it beat the
  current default (`weight_scale=1.0`) by, in average Brier score
- the **median best `weight_scale`** across all evaluated leagues — near
  `1.0` means the current default is about right; consistently higher or
  lower is a signal worth acting on
- leagues skipped for having too few matches

Once it's done, a **"Copy Results"** button copies a plain-text/tab-separated
report to the clipboard (via `buildCalibrationSweepSummaryText` in
`soccer_ratings/static/app.js`) — the per-league table pastes cleanly into a
spreadsheet, and the whole thing reads fine pasted into chat or email too.

Also available headlessly:

```bash
POST /api/calibration-sweep      # starts the job, returns 202 + job payload
GET  /api/calibration-sweep/status?job_id=...
```

## Data maintenance: duplicate team/match rows

An older version of `_upsert_team` (`soccer_ratings/db.py`) inserted a fresh
`teams` row every time it saw a team without a discovered `team_path` —
typically a historical opponent outside a league's own roster, like a
relegated/promoted team. Since Postgres treats `NULL` as never equal to
`NULL` under a `UNIQUE` constraint, `ON CONFLICT (team_path)` never fired
for those rows, so every re-import minted a new team row for the same team
name, which cascaded into duplicate `matches` rows once the "same" fixture
ended up pointing at two different team ids. `_upsert_team` now looks
NULL-path teams up by name first, so this can't happen going forward.

To clean up rows a database already has from before this fix, run the
**"Merge Duplicate Teams & Matches"** button in the `/admin` page's **Data
Maintenance** section, or headlessly:

```bash
python3 app.py dedupe-history
```

Both call `merge_duplicate_teams` in `soccer_ratings/db.py`, which merges
duplicate team rows (preferring one that actually has a `team_path`),
repoints `matches`/`rating_snapshots` at the surviving row, drops the match
rows that become exact duplicates once both sides are remapped (keeping the
most recently touched copy of each fixture), and deletes the now-orphaned
team rows. Safe to run repeatedly — a database with no duplicates is a
no-op.

## Tests

```bash
python3 -m unittest discover -s tests
```
