from __future__ import annotations

from .odds import calculate_match_probabilities

OUTCOMES = ("home", "draw", "away")

_CALIBRATION_BUCKET_SIZE = 0.1


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
    edge_threshold_percent: float = 5.0,
    stake: float = 1.0,
    tuning_params: dict[str, float] | None = None,
) -> dict | None:
    """Score one completed historical match: model vs market.

    Uses the ratings and bookmaker odds that were stored on the match row
    itself (i.e. as they were when the match was actually played), and the
    plain ratings-only model (no historical calibration) so the backtest
    never leaks knowledge of other matches — including future ones — into
    a match's own prediction.

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
    elo_divisor = tuning_params.get("elo_divisor", 400.0)
    draw_max = tuning_params.get("draw_max", 0.30)
    draw_divisor = tuning_params.get("draw_divisor", 500.0)
    draw_min = tuning_params.get("draw_min", 0.18)
    home_advantage = tuning_params.get("home_advantage", 0.0)

    model_probabilities = calculate_match_probabilities(
        float(home_rating),
        float(away_rating),
        elo_divisor=elo_divisor,
        draw_max=draw_max,
        draw_divisor=draw_divisor,
        draw_min=draw_min,
        home_advantage=home_advantage,
    )
    market_probabilities, overround = implied_probabilities_from_odds(
        float(home_odds), float(draw_odds), float(away_odds)
    )
    outcome = match_outcome(int(home_goals), int(away_goals))
    market_odds = {"home": float(home_odds), "draw": float(draw_odds), "away": float(away_odds)}

    edges = {
        key: round((model_probabilities[key] - market_probabilities[key]) * 100.0, 2)
        for key in OUTCOMES
    }
    brier = sum(
        (model_probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in OUTCOMES
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
        "market_probabilities": {key: round(value, 4) for key, value in market_probabilities.items()},
        "market_odds": market_odds,
        "overround": round(overround, 4),
        "edges": edges,
        "brier": round(brier, 4),
        "value_bets": value_bets,
        "staked": round(staked, 2),
        "profit": round(profit, 2),
    }


def run_league_backtest(
    matches: list[dict],
    edge_threshold_percent: float = 5.0,
    stake: float = 1.0,
    tuning_params: dict[str, float] | None = None,
) -> dict:
    """Replay a league's stored match history through the model and grade it
    against both what actually happened and what the market priced in.
    """
    evaluated = [
        row
        for row in (
            evaluate_match(
                match,
                edge_threshold_percent=edge_threshold_percent,
                stake=stake,
                tuning_params=tuning_params,
            )
            for match in matches
        )
        if row is not None
    ]

    if not evaluated:
        return {
            "matches_evaluated": 0,
            "edge_threshold_percent": round(edge_threshold_percent, 2),
            "stake": stake,
        }

    avg_brier = sum(row["brier"] for row in evaluated) / len(evaluated)
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

    return {
        "matches_evaluated": len(evaluated),
        "edge_threshold_percent": round(edge_threshold_percent, 2),
        "stake": stake,
        "avg_brier": round(avg_brier, 4),
        "pick_accuracy_percent": round(pick_hits / len(evaluated) * 100.0, 1),
        "calibration": _build_calibration_buckets(evaluated),
        "value_bet_matches": len(value_rows),
        "value_bet_count": value_bet_count,
        "value_bet_wins": value_bet_wins,
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
