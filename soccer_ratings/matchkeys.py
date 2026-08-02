"""Canonical identity, ordering, and de-duplication for match rows.

Match history arrives from two independent paths (Postgres and the cached
scrape file) and, historically, the same fixture could appear two or three
times in the result: duplicate `teams` rows (same club, different
team_path) each produce their own `matches` row, since the matches unique
constraint keys on team *id*, not name. Every duplicate silently multiplies
that fixture's weight in a backtest — its stake, its profit, its
calibration bucket — so scoring has to collapse them before it counts
anything.

Dates get the same treatment. The rest of the codebase reordered "dd.mm.yy"
into "yy.mm.dd" and sorted the resulting *string*, which happens to work
for one format and silently misorders anything else (a "2024-05-11" row
sorts before every dotted date). Walk-forward evaluation depends on
chronological order being right, so ordering goes through a real date parse
here.
"""

from __future__ import annotations

from datetime import date

from .odds import parse_date

# Sorts before every real date, so unparseable rows land at the start of an
# ascending sort (and the end of a descending one) instead of wherever
# string comparison happened to put them.
_UNPARSEABLE_DATE = date.min


def normalize_name(value) -> str:
    """Case- and whitespace-insensitive form of a team/competition name, so
    "Arsenal FC" and "arsenal fc " are recognized as the same club.
    """
    return " ".join(str(value or "").split()).casefold()


def chronological_key(value) -> tuple[date, str]:
    """Sort key that orders match dates chronologically for real.

    Falls back to the raw text for anything parse_date can't read, so the
    ordering stays deterministic (and the unparseable rows stay grouped)
    rather than raising mid-sort.
    """
    parsed = parse_date(value)
    if parsed is not None:
        return (parsed, "")
    return (_UNPARSEABLE_DATE, str(value or "").strip())


def sort_matches_by_date(matches: list[dict], *, reverse: bool = False) -> list[dict]:
    """Order matches by real date, tie-broken by competition and team names
    so equal-dated rows come out in a stable, reproducible order.
    """
    return sorted(
        matches,
        key=lambda match: (
            chronological_key(match.get("date")),
            normalize_name(match.get("competition")),
            normalize_name(match.get("home_team")),
            normalize_name(match.get("away_team")),
        ),
        reverse=reverse,
    )


def match_identity_key(match: dict) -> tuple:
    """What makes two rows the same fixture: date, competition, and the two
    clubs — by normalized *name*, deliberately not by team id, since
    duplicate team rows are the very thing this is here to collapse.
    """
    return (
        chronological_key(match.get("date")),
        normalize_name(match.get("competition")),
        normalize_name(match.get("home_team")),
        normalize_name(match.get("away_team")),
    )


def _snapshot_rank(match: dict) -> tuple:
    """How preferable one duplicate of a fixture is over another.

    Higher sorts better. The rule, in order: a settled result beats an
    unsettled one, a usable price beats a missing/nonsensical one, and among
    equals the most recently written row wins — that's the closest thing to
    "closing odds" the stored data offers, and it makes the choice a
    property of the row rather than of whatever order the query returned.
    """
    has_result = (
        match.get("home_goals") is not None and match.get("away_goals") is not None
    )
    odds = (match.get("home_odds"), match.get("draw_odds"), match.get("away_odds"))
    has_odds = all(value is not None and float(value) > 0 for value in odds)
    has_ratings = (
        match.get("home_rating") is not None and match.get("away_rating") is not None
    )
    # Written by the DB loader; absent on cached-scrape rows, where every
    # duplicate ranks equal here and the first-seen row wins.
    row_id = match.get("row_id")
    return (
        1 if has_result else 0,
        1 if has_odds else 0,
        1 if has_ratings else 0,
        int(row_id) if row_id is not None else -1,
    )


def dedupe_matches(matches: list[dict]) -> tuple[list[dict], int]:
    """Collapse repeated fixtures to one row each, keeping the best snapshot
    per _snapshot_rank.

    Returns the deduplicated matches (chronological, oldest first) and how
    many rows were dropped — the count is worth reporting rather than
    swallowing, because a nonzero value means something upstream is minting
    duplicates and the raw totals can't be trusted.
    """
    best: dict[tuple, dict] = {}
    dropped = 0

    for match in matches:
        key = match_identity_key(match)
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = match
            continue
        dropped += 1
        if _snapshot_rank(match) > _snapshot_rank(incumbent):
            best[key] = match

    return sort_matches_by_date(list(best.values())), dropped
