from __future__ import annotations

import math


def probability_to_decimal_odds(probability: float) -> float:
    if probability <= 0:
        return 0.0
    return round(1.0 / probability, 2)


def calculate_match_probabilities(home_rating: float, away_rating: float) -> dict[str, float]:
    """Convert a rating gap into 1X2 probabilities.

    Assumptions:
    - Home team's home rating is compared against away team's away rating.
    - The win split uses an Elo-style logistic curve.
    - Draw probability is highest when teams are evenly matched and shrinks as the gap grows.
    """

    rating_gap = home_rating - away_rating
    win_share = 1.0 / (1.0 + math.pow(10.0, -rating_gap / 400.0))
    draw_probability = 0.30 * math.exp(-abs(rating_gap) / 500.0)
    draw_probability = min(0.30, max(0.18, draw_probability))

    remaining = 1.0 - draw_probability
    home_probability = remaining * win_share
    away_probability = remaining * (1.0 - win_share)

    return {
        "home": round(home_probability, 4),
        "draw": round(draw_probability, 4),
        "away": round(away_probability, 4),
    }


def build_match_odds(home_rating: float, away_rating: float) -> dict[str, float]:
    probabilities = calculate_match_probabilities(home_rating, away_rating)
    return {
        "home": probability_to_decimal_odds(probabilities["home"]),
        "draw": probability_to_decimal_odds(probabilities["draw"]),
        "away": probability_to_decimal_odds(probabilities["away"]),
    }


def calculate_dnb_probabilities(probabilities: dict[str, float]) -> dict[str, float]:
    non_draw_probability = probabilities["home"] + probabilities["away"]
    if non_draw_probability <= 0:
        return {"home": 0.0, "away": 0.0}

    return {
        "home": round(probabilities["home"] / non_draw_probability, 4),
        "away": round(probabilities["away"] / non_draw_probability, 4),
    }


def build_dnb_odds(home_rating: float, away_rating: float) -> dict[str, float]:
    dnb_probabilities = calculate_dnb_probabilities(
        calculate_match_probabilities(home_rating, away_rating)
    )
    return {
        "home": probability_to_decimal_odds(dnb_probabilities["home"]),
        "away": probability_to_decimal_odds(dnb_probabilities["away"]),
    }


def apply_shin_margin(probabilities: dict[str, float], margin_percent: float) -> dict[str, object]:
    target_overround = 1.0 + max(0.0, margin_percent) / 100.0
    if target_overround <= 1.0:
        return {
            "probabilities": {key: round(value, 4) for key, value in probabilities.items()},
            "odds": {key: probability_to_decimal_odds(value) for key, value in probabilities.items()},
            "z": 0.0,
            "overround": 1.0,
        }

    max_overround = _calculate_shin_overround(probabilities, 0.999999)
    z = 0.999999 if target_overround >= max_overround else _solve_shin_z(probabilities, target_overround)
    adjusted_probabilities = _calculate_shin_book_probabilities(probabilities, z)

    return {
        "probabilities": adjusted_probabilities,
        "odds": {key: probability_to_decimal_odds(value) for key, value in adjusted_probabilities.items()},
        "z": round(z, 6),
        "overround": round(sum(adjusted_probabilities.values()), 6),
    }


def _calculate_shin_book_probabilities(probabilities: dict[str, float], z: float) -> dict[str, float]:
    return {
        key: round(value, 4)
        for key, value in _calculate_shin_book_probabilities_raw(probabilities, z).items()
    }


def _calculate_shin_book_probabilities_raw(probabilities: dict[str, float], z: float) -> dict[str, float]:
    weights = {
        key: math.sqrt(value * (z + (1.0 - z) * value))
        for key, value in probabilities.items()
    }
    scale = sum(weights.values())
    if scale <= 0:
        return {key: 0.0 for key in probabilities}
    return {key: scale * weight for key, weight in weights.items()}


def _calculate_shin_overround(probabilities: dict[str, float], z: float) -> float:
    return sum(_calculate_shin_book_probabilities_raw(probabilities, z).values())


def _solve_shin_z(probabilities: dict[str, float], target_overround: float) -> float:
    low = 0.0
    high = 0.999999
    for _ in range(60):
        mid = (low + high) / 2.0
        overround = _calculate_shin_overround(probabilities, mid)
        if overround < target_overround:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0
