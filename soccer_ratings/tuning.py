from __future__ import annotations

from .backtest import implied_probabilities_from_odds, match_outcome
from .odds import (
    calculate_match_probabilities,
    calibrate_probabilities_with_history,
    summarize_historical_match_context,
)

OUTCOMES = ("home", "draw", "away")

DEFAULT_WEIGHT_SCALES = (0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
DEFAULT_MIN_MATCHES = 30


def _date_sort_key(value) -> str:
    """Rearrange a dd.mm.yy date so string ordering matches chronology."""
    text = str(value or "").strip()
    parts = text.split(".")
    if len(parts) == 3:
        day, month, year = parts
        return f"{year}.{month}.{day}"
    return text


def _brier_score(probabilities: dict[str, float], outcome: str) -> float:
    return sum(
        (probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in OUTCOMES
    )


def walk_forward_predictions(matches: list[dict], weight_scale: float) -> list[dict]:
    """Chronologically replay a league's matches, predicting each one using
    only the history strictly before it. This is what makes the sweep a
    fair test of a weight_scale: calibrate_probabilities_with_history's
    default usage in the live app rebuilds historical_context from the
    same call, but a naive backtest that hands it the *whole* league's
    history (past and future relative to the match being scored) would let
    each prediction see results that hadn't happened yet.
    """
    ordered = sorted(matches, key=lambda match: _date_sort_key(match.get("date")))
    predictions: list[dict] = []

    for index, match in enumerate(ordered):
        home_rating = match.get("home_rating")
        away_rating = match.get("away_rating")
        home_goals = match.get("home_goals")
        away_goals = match.get("away_goals")
        if None in (home_rating, away_rating, home_goals, away_goals):
            continue

        prior_matches = ordered[:index]
        rating_gap = float(home_rating) - float(away_rating)
        historical_context = summarize_historical_match_context(
            prior_matches, target_rating_gap=rating_gap
        )

        base_probabilities = calculate_match_probabilities(float(home_rating), float(away_rating))
        probabilities = calibrate_probabilities_with_history(
            base_probabilities, historical_context, weight_scale=weight_scale
        )

        outcome = match_outcome(int(home_goals), int(away_goals))
        predicted_outcome = max(probabilities, key=probabilities.get)

        row = {
            "date": match.get("date"),
            "home_team": match.get("home_team"),
            "away_team": match.get("away_team"),
            "outcome": outcome,
            "probabilities": probabilities,
            "brier": round(_brier_score(probabilities, outcome), 4),
            "correct_pick": predicted_outcome == outcome,
        }

        home_odds = match.get("home_odds")
        draw_odds = match.get("draw_odds")
        away_odds = match.get("away_odds")
        if home_odds and draw_odds and away_odds and home_odds > 0 and draw_odds > 0 and away_odds > 0:
            market_probabilities, _ = implied_probabilities_from_odds(
                float(home_odds), float(draw_odds), float(away_odds)
            )
            row["market_brier"] = round(_brier_score(market_probabilities, outcome), 4)

        predictions.append(row)

    return predictions


def evaluate_weight_scale(matches: list[dict], weight_scale: float) -> dict:
    predictions = walk_forward_predictions(matches, weight_scale)
    if not predictions:
        return {"weight_scale": weight_scale, "matches_evaluated": 0}

    avg_brier = sum(row["brier"] for row in predictions) / len(predictions)
    pick_accuracy = sum(1 for row in predictions if row["correct_pick"]) / len(predictions)

    market_briers = [row["market_brier"] for row in predictions if "market_brier" in row]
    avg_market_brier = sum(market_briers) / len(market_briers) if market_briers else None

    return {
        "weight_scale": weight_scale,
        "matches_evaluated": len(predictions),
        "avg_brier": round(avg_brier, 4),
        "pick_accuracy_percent": round(pick_accuracy * 100.0, 1),
        "avg_market_brier": round(avg_market_brier, 4) if avg_market_brier is not None else None,
        "beats_market": (avg_market_brier is not None and avg_brier < avg_market_brier),
    }


def sweep_weight_scales(
    matches: list[dict],
    weight_scales: tuple[float, ...] = DEFAULT_WEIGHT_SCALES,
    min_matches: int = DEFAULT_MIN_MATCHES,
) -> dict:
    """Try each candidate weight_scale against a league's real history and
    report which minimizes Brier score (lower is better-calibrated).

    weight_scale 0.0 is the ratings-only model (no history blended in) and
    1.0 is the current hand-picked default — both are always included in
    weight_scales's default so the sweep answers "does calibration help at
    all, and is the current amount of trust in history about right."

    Requires min_matches completed matches so small leagues with too
    little history to draw a real conclusion from don't get tuned on
    noise; below that threshold the sweep is skipped entirely.
    """
    completed = [
        match
        for match in matches
        if match.get("home_goals") is not None and match.get("away_goals") is not None
    ]
    if len(completed) < min_matches:
        return {
            "matches_available": len(completed),
            "min_matches_required": min_matches,
            "results": [],
            "best": None,
        }

    results = [evaluate_weight_scale(matches, scale) for scale in weight_scales]
    best = min(results, key=lambda result: result["avg_brier"])

    return {
        "matches_available": len(completed),
        "min_matches_required": min_matches,
        "results": results,
        "best": best,
        "current_default_scale": 1.0,
    }
