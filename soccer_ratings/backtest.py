from __future__ import annotations

from datetime import datetime, timezone

from .matchkeys import dedupe_matches
from .odds import DEFAULT_MARKET_WEIGHT, DEFAULT_RHO, blend_with_market, calculate_match_probabilities, parse_date

OUTCOMES = ("home", "draw", "away")

# Ratings written this long after kickoff are treated as suspect rather than
# as-of-match. A day of slack absorbs the ordinary case: a match played in
# the evening whose row is written by an overnight import, with ratings that
# still reflect the pre-match state.
RATING_CAPTURE_GRACE_HOURS = 24.0

_CALIBRATION_BUCKET_SIZE = 0.1

# edge_threshold_percent is now a *relative* edge (model_p / raw_implied_p -
# 1) rather than an absolute percentage-point gap, so it needs a higher bar
# than the old 5.0pp default to mean roughly the same thing — 5% relative
# edge is trivially crossed by noise, especially on long-shot prices.
DEFAULT_EDGE_THRESHOLD_PERCENT = 10.0

# A side with more than this share of all flagged value bets makes the
# backtest's ROI indistinguishable from "the model is systematically biased
# toward this side" rather than "the model has found real edge" — see
# value_bets_by_side/roi_trustworthy below.
MAX_TRUSTWORTHY_SIDE_SHARE = 0.6


def implied_probabilities_from_odds(
    home_odds: float, draw_odds: float, away_odds: float
) -> tuple[dict[str, float], float]:
    """De-vig bookmaker odds into a probability triple that sums to 1.0.

    Returns the normalized probabilities plus the raw overround (>1.0 for
    any real bookmaker price), via simple proportional de-vigging.
    """
    raw = {
        "home": 1.0 / home_odds if home_odds > 0 else 0.0,
        "draw": 1.0 / draw_odds if draw_odds > 0 else 0.0,
        "away": 1.0 / away_odds if away_odds > 0 else 0.0,
    }
    overround = sum(raw.values())
    if overround <= 0:
        return {"home": 0.0, "draw": 0.0, "away": 0.0}, 0.0
    return {key: value / overround for key, value in raw.items()}, overround


def match_outcome(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def evaluate_match(
    match: dict,
    edge_threshold_percent: float = DEFAULT_EDGE_THRESHOLD_PERCENT,
    stake: float = 1.0,
    tuning_params: dict[str, float] | None = None,
    market_weight: float = DEFAULT_MARKET_WEIGHT,
) -> dict | None:
    """Score one completed historical match: model vs market.

    Uses the ratings and bookmaker odds that were stored on the match row
    itself (i.e. as they were when the match was actually played), and the
    plain ratings-only model (no historical calibration) so the backtest
    never leaks knowledge of other matches — including future ones — into
    a match's own prediction.

    The raw ratings-only model is blended toward the de-vigged market
    (blend_with_market, weighted market_weight toward the market) before
    edges/value bets are derived from it — the market anchor corrects the
    model's systematic biases and confidence errors, so what actually gets
    bet is the corrected view, not the raw one. Both are reported (as
    "model_probabilities"/"brier" for the corrected view and
    "raw_model_probabilities"/"raw_model_brier" for the uncorrected one),
    along with "market_brier", so the market can be scored as a baseline
    alongside both.

    Edges are relative, against the raw (vigged) price actually on offer —
    (model_p / raw_implied_p - 1) * 100 — not the de-vigged market
    probability: the vig is money you'd actually pay, and a flat
    percentage-point edge means very different things at a 10% price versus
    a 70% one, where relative edge is comparable across the whole range.

    Returns None if the match is missing anything needed to score it
    (unplayed fixture, missing odds, etc).
    """
    home_rating = match.get("home_rating")
    away_rating = match.get("away_rating")
    home_odds = match.get("home_odds")
    draw_odds = match.get("draw_odds")
    away_odds = match.get("away_odds")
    home_goals = match.get("home_goals")
    away_goals = match.get("away_goals")

    if None in (home_rating, away_rating, home_odds, draw_odds, away_odds, home_goals, away_goals):
        return None
    if home_odds <= 0 or draw_odds <= 0 or away_odds <= 0:
        return None

    # Load tuning parameters
    tuning_params = tuning_params or {}
    home_advantage = tuning_params.get("home_advantage", 0.0)
    rho = tuning_params.get("rho", DEFAULT_RHO)

    raw_model_probabilities = calculate_match_probabilities(
        float(home_rating),
        float(away_rating),
        home_advantage=home_advantage,
        rho=rho,
    )
    market_probabilities, overround = implied_probabilities_from_odds(
        float(home_odds), float(draw_odds), float(away_odds)
    )
    model_probabilities = blend_with_market(
        raw_model_probabilities, market_probabilities, market_weight=market_weight
    )
    outcome = match_outcome(int(home_goals), int(away_goals))
    market_odds = {"home": float(home_odds), "draw": float(draw_odds), "away": float(away_odds)}

    # The raw, vigged implied price — what you'd actually pay to place the
    # bet — as opposed to market_probabilities, which has the overround
    # stripped out and is only used for Brier scoring/blending above.
    raw_implied_probabilities = {
        key: (1.0 / market_odds[key]) if market_odds[key] > 0 else 0.0 for key in OUTCOMES
    }
    edges = {
        key: (
            round((model_probabilities[key] / raw_implied_probabilities[key] - 1.0) * 100.0, 2)
            if raw_implied_probabilities[key] > 0
            else 0.0
        )
        for key in OUTCOMES
    }

    def _brier(probabilities: dict[str, float]) -> float:
        return sum(
            (probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in OUTCOMES
        )

    value_bets = [key for key in OUTCOMES if edges[key] >= edge_threshold_percent]
    staked = stake * len(value_bets)
    profit = 0.0
    for key in value_bets:
        profit += stake * (market_odds[key] - 1.0) if key == outcome else -stake

    return {
        "date": match.get("date"),
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
        "competition": match.get("competition"),
        "result": match.get("result"),
        "outcome": outcome,
        "model_probabilities": model_probabilities,
        "raw_model_probabilities": raw_model_probabilities,
        "market_probabilities": {key: round(value, 4) for key, value in market_probabilities.items()},
        "raw_implied_probabilities": {key: round(value, 4) for key, value in raw_implied_probabilities.items()},
        "market_odds": market_odds,
        "overround": round(overround, 4),
        "edges": edges,
        "brier": round(_brier(model_probabilities), 4),
        "raw_model_brier": round(_brier(raw_model_probabilities), 4),
        "market_brier": round(_brier(market_probabilities), 4),
        "value_bets": value_bets,
        "staked": round(staked, 2),
        "profit": round(profit, 2),
    }


def run_league_backtest(
    matches: list[dict],
    edge_threshold_percent: float = DEFAULT_EDGE_THRESHOLD_PERCENT,
    stake: float = 1.0,
    tuning_params: dict[str, float] | None = None,
    market_weight: float = DEFAULT_MARKET_WEIGHT,
) -> dict:
    """Replay a league's stored match history through the model and grade it
    against both what actually happened and what the market priced in.

    Repeated fixtures are collapsed first (see soccer_ratings.matchkeys):
    the same match arriving two or three times would otherwise count two or
    three times in the Brier average, the calibration buckets, and — most
    damagingly — the staked/profit totals, turning one bad bet into three.
    "duplicates_dropped" reports how many rows that removed, so a
    regression upstream shows up in the payload instead of hiding inside a
    plausible-looking ROI.
    """
    matches, duplicates_dropped = dedupe_matches(matches)
    ratings_as_of = _build_ratings_as_of_report(matches)

    evaluated = [
        row
        for row in (
            evaluate_match(
                match,
                edge_threshold_percent=edge_threshold_percent,
                stake=stake,
                tuning_params=tuning_params,
                market_weight=market_weight,
            )
            for match in matches
        )
        if row is not None
    ]

    if not evaluated:
        return {
            "matches_evaluated": 0,
            "duplicates_dropped": duplicates_dropped,
            "ratings_as_of": ratings_as_of,
            "edge_threshold_percent": round(edge_threshold_percent, 2),
            "stake": stake,
            "market_weight": round(market_weight, 2),
        }

    avg_brier = sum(row["brier"] for row in evaluated) / len(evaluated)
    avg_raw_model_brier = sum(row["raw_model_brier"] for row in evaluated) / len(evaluated)
    avg_market_brier = sum(row["market_brier"] for row in evaluated) / len(evaluated)
    pick_hits = sum(
        1
        for row in evaluated
        if max(row["model_probabilities"], key=row["model_probabilities"].get) == row["outcome"]
    )

    value_rows = [row for row in evaluated if row["value_bets"]]
    total_staked = sum(row["staked"] for row in value_rows)
    total_profit = sum(row["profit"] for row in value_rows)
    value_bet_count = sum(len(row["value_bets"]) for row in value_rows)
    value_bet_wins = sum(
        1 for row in value_rows for key in row["value_bets"] if key == row["outcome"]
    )

    beats_market = avg_brier < avg_market_brier
    value_bets_by_side = _build_value_bets_by_side(evaluated, stake)
    sides_balanced, dominant_side, dominant_share = _check_side_balance(
        value_bets_by_side, value_bet_count
    )

    roi_caveats = []
    if value_bet_count > 0 and not beats_market:
        roi_caveats.append(
            "The blended model's Brier score does not beat the market's — ROI may reflect "
            "leftover model bias rather than genuine skill."
        )
    if sides_balanced is False:
        roi_caveats.append(
            f"{round(dominant_share * 100.0, 1)}% of value bets are on '{dominant_side}' — ROI "
            "may just be measuring a systematic model bias toward that side, not real edge."
        )
    roi_trustworthy = bool(value_bet_count > 0 and beats_market and sides_balanced)

    return {
        "matches_evaluated": len(evaluated),
        "duplicates_dropped": duplicates_dropped,
        "ratings_as_of": ratings_as_of,
        "edge_threshold_percent": round(edge_threshold_percent, 2),
        "stake": stake,
        "market_weight": round(market_weight, 2),
        "avg_brier": round(avg_brier, 4),
        "avg_raw_model_brier": round(avg_raw_model_brier, 4),
        "avg_market_brier": round(avg_market_brier, 4),
        "beats_market": beats_market,
        "pick_accuracy_percent": round(pick_hits / len(evaluated) * 100.0, 1),
        "calibration": _build_calibration_buckets(evaluated),
        "value_bet_matches": len(value_rows),
        "value_bet_count": value_bet_count,
        "value_bet_wins": value_bet_wins,
        "value_bets_by_side": value_bets_by_side,
        "sides_balanced": sides_balanced,
        "roi_trustworthy": roi_trustworthy,
        "roi_caveats": roi_caveats,
        "hit_rate_percent": (
            round(value_bet_wins / value_bet_count * 100.0, 1) if value_bet_count > 0 else None
        ),
        "total_staked": round(total_staked, 2),
        "total_profit": round(total_profit, 2),
        "roi_percent": (
            round(total_profit / total_staked * 100.0, 2) if total_staked > 0 else None
        ),
        "matches": evaluated,
    }


def _build_ratings_as_of_report(matches: list[dict]) -> dict:
    """Check whether the ratings stored on each match row plausibly predate
    its kickoff.

    The backtest scores every match using the home_rating/away_rating saved
    on the row, on the assumption those are the ratings as they stood when
    the match was played. Nothing in the data model enforces that: if a row
    is (re)written after the result is known, it can carry ratings that
    already reflect the outcome being predicted, and the backtest would
    score the model on knowledge it could not have had.

    This does not silently drop anything — the point is to make the
    assumption falsifiable. "unknown" rows are ones whose capture time was
    never recorded (everything imported before rating_captured_at existed),
    which is not evidence of leakage but is not evidence against it either.
    """
    total = len(matches)
    verified = 0
    suspect = 0
    unknown = 0
    latest_lag_hours = 0.0

    for match in matches:
        captured_at = match.get("rating_captured_at")
        match_date = parse_date(match.get("date"))
        if captured_at is None or match_date is None:
            unknown += 1
            continue

        if isinstance(captured_at, str):
            captured_dt = _parse_timestamp(captured_at)
            if captured_dt is None:
                unknown += 1
                continue
        elif isinstance(captured_at, datetime):
            captured_dt = captured_at
        else:
            unknown += 1
            continue

        if captured_dt.tzinfo is None:
            captured_dt = captured_dt.replace(tzinfo=timezone.utc)

        kickoff = datetime(
            match_date.year, match_date.month, match_date.day, tzinfo=timezone.utc
        )
        lag_hours = (captured_dt - kickoff).total_seconds() / 3600.0
        if lag_hours > RATING_CAPTURE_GRACE_HOURS:
            suspect += 1
            latest_lag_hours = max(latest_lag_hours, lag_hours)
        else:
            verified += 1

    warnings = []
    if suspect > 0:
        warnings.append(
            f"{suspect} of {total} matches carry ratings written more than "
            f"{round(RATING_CAPTURE_GRACE_HOURS)}h after kickoff (worst: "
            f"{round(latest_lag_hours / 24.0)} days) — those predictions may be "
            "scored on ratings that already reflect the result."
        )
    if unknown > 0:
        warnings.append(
            f"{unknown} of {total} matches have no rating capture time recorded, so "
            "whether their ratings predate kickoff cannot be verified."
        )

    return {
        "matches": total,
        "verified_before_kickoff": verified,
        "captured_after_kickoff": suspect,
        "unknown": unknown,
        "grace_hours": RATING_CAPTURE_GRACE_HOURS,
        # Only true when every row was positively checked — "no warnings"
        # must not be reachable by simply never recording the timestamp.
        "trustworthy": bool(total > 0 and verified == total),
        "warnings": warnings,
    }


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _build_value_bets_by_side(evaluated: list[dict], stake: float) -> dict[str, dict]:
    """Break the flat-stake value-bet simulation down per outcome side, so a
    lopsided book (e.g. ~all away bets) is visible directly instead of
    hiding inside a single blended ROI number.
    """
    totals = {key: {"count": 0, "wins": 0, "staked": 0.0, "profit": 0.0} for key in OUTCOMES}
    for row in evaluated:
        for key in row["value_bets"]:
            side = totals[key]
            side["count"] += 1
            side["staked"] += stake
            if key == row["outcome"]:
                side["wins"] += 1
                side["profit"] += stake * (row["market_odds"][key] - 1.0)
            else:
                side["profit"] -= stake

    by_side = {}
    for key, side in totals.items():
        by_side[key] = {
            "count": side["count"],
            "wins": side["wins"],
            "hit_rate_percent": (
                round(side["wins"] / side["count"] * 100.0, 1) if side["count"] > 0 else None
            ),
            "staked": round(side["staked"], 2),
            "profit": round(side["profit"], 2),
            "roi_percent": (
                round(side["profit"] / side["staked"] * 100.0, 2) if side["staked"] > 0 else None
            ),
        }
    return by_side


def _check_side_balance(
    value_bets_by_side: dict[str, dict], value_bet_count: int
) -> tuple[bool | None, str | None, float]:
    """Whether value bets are spread across outcome sides rather than piled
    onto one — a single side above MAX_TRUSTWORTHY_SIDE_SHARE of all bets
    means the "edge" is most likely a systematic model bias toward that
    side (see the analysis that motivated this: ~all "value" was on away
    bets), not evidence the model is finding real mispricing.

    Returns (is_balanced, dominant_side, dominant_share). is_balanced is
    None when there are no value bets to judge at all.
    """
    if value_bet_count <= 0:
        return None, None, 0.0

    dominant_side, dominant_count = max(
        ((key, side["count"]) for key, side in value_bets_by_side.items()),
        key=lambda item: item[1],
    )
    dominant_share = dominant_count / value_bet_count
    return dominant_share <= MAX_TRUSTWORTHY_SIDE_SHARE, dominant_side, dominant_share


def _build_calibration_buckets(evaluated: list[dict]) -> list[dict]:
    """Bucket every (predicted probability, did it happen) pair the model
    produced — flattening home/draw/away into one pool — by decile, so
    'when the model said ~40%, how often did it actually happen?' is
    answerable directly from the historical record.
    """
    bucket_count = round(1.0 / _CALIBRATION_BUCKET_SIZE)
    predicted_sums = [0.0] * bucket_count
    actual_sums = [0.0] * bucket_count
    counts = [0] * bucket_count

    for row in evaluated:
        for key in OUTCOMES:
            predicted = row["model_probabilities"][key]
            actual = 1.0 if row["outcome"] == key else 0.0
            index = min(bucket_count - 1, int(predicted / _CALIBRATION_BUCKET_SIZE))
            predicted_sums[index] += predicted
            actual_sums[index] += actual
            counts[index] += 1

    buckets = []
    for index, count in enumerate(counts):
        if count == 0:
            continue
        buckets.append(
            {
                "range_low": round(index * _CALIBRATION_BUCKET_SIZE * 100.0),
                "range_high": round((index + 1) * _CALIBRATION_BUCKET_SIZE * 100.0),
                "predicted_percent": round(predicted_sums[index] / count * 100.0, 1),
                "actual_percent": round(actual_sums[index] / count * 100.0, 1),
                "count": count,
            }
        )
    return buckets
