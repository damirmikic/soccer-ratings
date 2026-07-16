from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from soccer_ratings.env import load_env_file
from soccer_ratings.backtest import run_league_backtest
from soccer_ratings.tuning import DEFAULT_WEIGHT_SCALES, sweep_weight_scales, sweep_league_parameters
from soccer_ratings.client import (
    DEFAULT_URL,
    build_and_cache_league_history,
    fetch_all_country_league_ratings,
    fetch_country_leagues,
    fetch_country_league_ratings,
    fetch_league_history,
    fetch_league_home_away_ratings,
    fetch_league_ratings,
    fetch_rankings,
    fetch_team_history,
)
from soccer_ratings.db import (
    import_all_history,
    import_country_rankings,
    import_country_history,
    import_league_history,
    import_league_ratings,
    init_db,
    load_all_history_matches,
    load_league_history_matches,
    matches_to_csv,
    refresh_known_history,
    update_league_tuning_parameters,
)
from soccer_ratings.dashboard import DashboardBindError, run_dashboard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch country, league, and team ratings from soccer-rating.com."
    )
    subparsers = parser.add_subparsers(dest="command")

    countries_parser = subparsers.add_parser(
        "countries",
        help="Fetch country rankings.",
    )
    countries_parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Ranking page URL to fetch.",
    )

    leagues_parser = subparsers.add_parser(
        "leagues",
        help="Fetch leagues for a country page.",
    )
    leagues_parser.add_argument(
        "--country-url",
        required=True,
        help="Country path or URL, for example /England/.",
    )

    ratings_parser = subparsers.add_parser(
        "ratings",
        help="Fetch team ratings for a league page.",
    )
    ratings_parser.add_argument(
        "--league-url",
        required=True,
        help="League path or URL, for example /England/UK1/.",
    )
    ratings_parser.add_argument(
        "--mode",
        default="general",
        choices=["general", "home", "away"],
        help="Rating mode to fetch.",
    )

    team_history_parser = subparsers.add_parser(
        "team-history",
        help="Fetch match history for a team page.",
    )
    team_history_parser.add_argument(
        "--team-url",
        required=True,
        help="Team path or URL, for example /Manchester-City/220/.",
    )
    team_history_parser.add_argument(
        "--team-name",
        help="Optional focal team name if the page header should be overridden.",
    )

    league_history_parser = subparsers.add_parser(
        "league-history",
        help="Fetch and dedupe historical matches for all teams in a league.",
    )
    league_history_parser.add_argument(
        "--league-url",
        required=True,
        help="League path or URL, for example /England/UK1/.",
    )
    league_history_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force rebuilding the cached league history dataset.",
    )

    init_db_parser = subparsers.add_parser(
        "init-db",
        help="Initialize the Postgres schema using DATABASE_URL.",
    )
    init_db_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    import_countries_parser = subparsers.add_parser(
        "import-country-rankings",
        help="Fetch country rankings and store them in Postgres.",
    )
    import_countries_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    import_leagues_parser = subparsers.add_parser(
        "import-league-ratings",
        help="Fetch league ratings for a country and store them in Postgres.",
    )
    import_leagues_parser.add_argument(
        "--country-url",
        required=True,
        help="Country path or URL, for example /England/.",
    )
    import_leagues_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    import_history_parser = subparsers.add_parser(
        "import-league-history",
        help="Fetch deduped league history and store it in Postgres.",
    )
    import_history_parser.add_argument(
        "--league-url",
        required=True,
        help="League path or URL, for example /England/UK1/.",
    )
    import_history_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    import_country_history_parser = subparsers.add_parser(
        "import-country-history",
        help="Fetch and store deduped history for every league in a country.",
    )
    import_country_history_parser.add_argument(
        "--country-url",
        required=True,
        help="Country path or URL, for example /England/.",
    )
    import_country_history_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    import_all_history_parser = subparsers.add_parser(
        "import-all-history",
        help="Fetch and store deduped history for every ranked country and league.",
    )
    import_all_history_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    refresh_known_history_parser = subparsers.add_parser(
        "refresh-known-history",
        help=(
            "Re-import history for every country already imported into Postgres "
            "(DB-only discovery, no live scrape to find them). Intended for a "
            "scheduled nightly refresh."
        ),
    )
    refresh_known_history_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    export_history_parser = subparsers.add_parser(
        "export-history",
        aliases=["export-matches", "export-db-matches"],
        help="Export historical results and odds from imported matches in Postgres to CSV or JSON.",
    )
    export_history_parser.add_argument(
        "--league-url",
        help="Optional league path or URL to export, for example /England/UK1/.",
    )
    export_history_parser.add_argument(
        "--competition",
        help="Optional competition code to export, for example UK1.",
    )
    export_history_parser.add_argument(
        "--format",
        default="csv",
        choices=["csv", "json"],
        help="Output format (default: csv).",
    )
    export_history_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DIRECT_DATABASE_URL, then DATABASE_URL.",
    )

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Replay stored league history through the model and grade it against the market.",
    )
    backtest_parser.add_argument(
        "--league-url",
        required=True,
        help="League path or URL, for example /England/UK1/.",
    )
    backtest_parser.add_argument(
        "--edge-threshold",
        type=float,
        default=5.0,
        help="Minimum model-vs-market edge (percentage points) to count as a value bet.",
    )
    backtest_parser.add_argument(
        "--stake",
        type=float,
        default=1.0,
        help="Flat stake per value bet, in units.",
    )
    backtest_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DATABASE_URL.",
    )

    tune_calibration_parser = subparsers.add_parser(
        "tune-calibration",
        help=(
            "Walk-forward backtest a league at several history-calibration weights and report "
            "which minimizes Brier score, to check whether the model should trust league history "
            "more or less than the current default."
        ),
    )
    tune_calibration_parser.add_argument(
        "--league-url",
        required=True,
        help="League path or URL, for example /England/UK1/.",
    )
    tune_calibration_parser.add_argument(
        "--weight-scales",
        type=float,
        nargs="+",
        default=list(DEFAULT_WEIGHT_SCALES),
        help="Candidate weight_scale values to try (0.0 = ratings-only model, 1.0 = current default).",
    )
    tune_calibration_parser.add_argument(
        "--min-matches",
        type=int,
        default=30,
        help="Skip the sweep if the league has fewer completed matches than this (avoids tuning on noise).",
    )
    tune_calibration_parser.add_argument(
        "--database-url",
        help="Optional Postgres connection URL. Defaults to DATABASE_URL.",
    )
    tune_calibration_parser.add_argument(
        "--persist",
        action="store_true",
        help="Save the best-performing tuning parameters to the database.",
    )

    crawl_country_parser = subparsers.add_parser(
        "crawl-country",
        help="Fetch all league home/away ratings for a country.",
    )
    crawl_country_parser.add_argument(
        "--country-url",
        required=True,
        help="Country path or URL, for example /England/.",
    )
    crawl_country_parser.add_argument(
        "--include-general",
        action="store_true",
        help="Also fetch the general league ratings page.",
    )

    crawl_all_parser = subparsers.add_parser(
        "crawl-all",
        help="Fetch all countries and all league home/away ratings.",
    )
    crawl_all_parser.add_argument(
        "--include-general",
        action="store_true",
        help="Also fetch the general league ratings page.",
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Run a local dashboard with country and league dropdowns.",
    )
    dashboard_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind the dashboard server to.",
    )
    dashboard_parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to bind the dashboard server to.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON output.",
    )
    return parser


def main() -> int:
    load_env_file()
    args = build_parser().parse_args()
    if args.command in {None, "countries"}:
        payload = fetch_rankings(url=getattr(args, "url", DEFAULT_URL))
    elif args.command == "leagues":
        payload = fetch_country_leagues(args.country_url)
    elif args.command == "ratings":
        payload = fetch_league_ratings(args.league_url, mode=args.mode)
    elif args.command == "team-history":
        payload = fetch_team_history(args.team_url, focal_team=args.team_name)
    elif args.command == "league-history":
        payload = build_and_cache_league_history(
            args.league_url,
            force_refresh=args.refresh,
        )
    elif args.command == "init-db":
        init_db(args.database_url)
        payload = {"initialized": True}
    elif args.command == "import-country-rankings":
        payload = import_country_rankings(args.database_url)
    elif args.command == "import-league-ratings":
        payload = import_league_ratings(args.country_url, args.database_url)
    elif args.command == "import-league-history":
        payload = import_league_history(args.league_url, args.database_url)
    elif args.command == "import-country-history":
        payload = import_country_history(args.country_url, args.database_url)
    elif args.command == "import-all-history":
        payload = import_all_history(args.database_url)
    elif args.command == "refresh-known-history":
        payload = refresh_known_history(args.database_url)
    elif args.command in {"export-history", "export-matches", "export-db-matches"}:
        if args.league_url:
            matches = load_league_history_matches(args.league_url, args.database_url)
        else:
            matches = load_all_history_matches(args.database_url, competition=args.competition)
        if args.format == "csv":
            output_csv = matches_to_csv(matches)
            if args.output:
                args.output.write_text(output_csv, encoding="utf-8")
            else:
                print(output_csv, end="")
            return 0
        payload = {"match_count": len(matches), "matches": matches}
    elif args.command == "backtest":
        matches = load_league_history_matches(args.league_url, args.database_url)
        payload = run_league_backtest(
            matches,
            edge_threshold_percent=args.edge_threshold,
            stake=args.stake,
        )
    elif args.command == "tune-calibration":
        matches = load_league_history_matches(args.league_url, args.database_url)
        payload = sweep_league_parameters(
            matches,
            weight_scales=tuple(args.weight_scales),
            min_matches=args.min_matches,
        )
        if args.persist and payload.get("best"):
            update_league_tuning_parameters(args.league_url, payload["best"], args.database_url)
            payload["persisted"] = True
    elif args.command == "crawl-country":
        payload = fetch_country_league_ratings(
            args.country_url,
            include_general=args.include_general,
        )
    elif args.command == "crawl-all":
        payload = fetch_all_country_league_ratings(
            include_general=args.include_general,
        )
    elif args.command == "dashboard":
        try:
            run_dashboard(host=args.host, port=args.port)
        except DashboardBindError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    output = json.dumps(payload, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
