from __future__ import annotations

import math

from .backtest import implied_probabilities_from_odds, match_outcome
from .matchkeys import sort_matches_by_date
from .odds import (
    DEFAULT_AWAY_GOAL_RATE,
    DEFAULT_AWAY_GOAL_SCALE,
    DEFAULT_HOME_GOAL_RATE,
    DEFAULT_HOME_GOAL_SCALE,
    DEFAULT_RHO,
    DEFAULT_TEMPERATURE,
    apply_temperature,
    calculate_match_probabilities,
    calibrate_probabilities_with_history,
    parse_date,
    summarize_historical_match_context,
)

OUTCOMES = ("home", "draw", "away")

DEFAULT_WEIGHT_SCALES = (0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
DEFAULT_MIN_MATCHES = 30

DEFAULT_HOME_ADVANTAGES = (0.0, 60.0, 100.0)
DEFAULT_RHOS = (-0.30, -0.20, -0.13, -0.05, 0.0)


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
    ordered = sort_matches_by_date(matches)
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
        "current_default_scale": 1.5,
    }


def summarize_league_sweeps(league_sweeps: list[dict]) -> dict | None:
    """Roll up one sweep_weight_scales() result per league (each with a
    "league"/"league_path"/"country" identifier merged in by the caller)
    into a single across-leagues recommendation: what weight_scale keeps
    coming out on top, and how much would using it improve Brier score
    over the current default (1.0)?
    """
    evaluated = [row for row in league_sweeps if row.get("best") is not None]
    if not evaluated:
        return None

    best_scales = sorted(row["best"]["weight_scale"] for row in evaluated)
    count = len(best_scales)
    median_best_scale = (
        best_scales[count // 2]
        if count % 2 == 1
        else (best_scales[count // 2 - 1] + best_scales[count // 2]) / 2.0
    )

    improvements = []
    for row in evaluated:
        default_result = next(
            (result for result in row["results"] if result["weight_scale"] == 1.0), None
        )
        if default_result is not None:
            improvements.append(default_result["avg_brier"] - row["best"]["avg_brier"])

    avg_brier_improvement = sum(improvements) / len(improvements) if improvements else None

    return {
        "leagues_evaluated": count,
        "median_best_weight_scale": round(median_best_scale, 3),
        "avg_brier_improvement_vs_default": (
            round(avg_brier_improvement, 4) if avg_brier_improvement is not None else None
        ),
    }


def sweep_league_parameters(
    matches: list[dict],
    weight_scales: tuple[float, ...] = (0.0, 0.5, 1.0, 1.5),
    home_advantages: tuple[float, ...] = DEFAULT_HOME_ADVANTAGES,
    rhos: tuple[float, ...] = DEFAULT_RHOS,
    min_matches: int = DEFAULT_MIN_MATCHES,
    decay_half_life_days: float = 182.5,
) -> dict:
    """Walk-forward calibrate a league over a multi-dimensional grid of
    probabilities parameters and weight scales, returning the set that
    minimizes the Brier score. Uses precomputation to optimize grid search.
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
            "default": None,
        }

    ordered = sort_matches_by_date(completed)

    # Precompute historical contexts to avoid redundant calculation in the loop
    precomputed = []
    for index, match in enumerate(ordered):
        home_rating = match.get("home_rating")
        away_rating = match.get("away_rating")
        home_goals = match.get("home_goals")
        away_goals = match.get("away_goals")
        if None in (home_rating, away_rating, home_goals, away_goals):
            continue

        prior_matches = ordered[:index]
        rating_gap = float(home_rating) - float(away_rating)
        target_date = parse_date(match.get("date"))

        historical_context = summarize_historical_match_context(
            prior_matches,
            target_rating_gap=rating_gap,
            target_date=target_date,
            decay_half_life_days=decay_half_life_days,
        )
        outcome = match_outcome(int(home_goals), int(away_goals))

        precomputed.append((float(home_rating), float(away_rating), historical_context, outcome))

    import itertools
    best_avg_brier = 999.0
    best_params = None
    baseline_brier = None

    for ws, ha, rho in itertools.product(weight_scales, home_advantages, rhos):
        total_brier = 0.0
        count = 0
        for home_rating, away_rating, historical_context, outcome in precomputed:
            base_probs = calculate_match_probabilities(
                home_rating,
                away_rating,
                home_advantage=ha,
                rho=rho,
            )
            probs = calibrate_probabilities_with_history(
                base_probs,
                historical_context,
                weight_scale=ws,
            )
            total_brier += _brier_score(probs, outcome)
            count += 1

        if count > 0:
            avg_brier = total_brier / count
            if avg_brier < best_avg_brier:
                best_avg_brier = avg_brier
                best_params = {
                    "weight_scale": ws,
                    "home_advantage": ha,
                    "rho": rho,
                }

            # Capture default baseline if present in the grid
            if (
                abs(ws - 1.5) < 1e-5
                and abs(ha - 0.0) < 1e-5
                and abs(rho - DEFAULT_RHO) < 1e-5
            ):
                baseline_brier = avg_brier

    # If baseline default parameters weren't explicitly in the grid, calculate it now
    if baseline_brier is None and precomputed:
        total_brier = 0.0
        for home_rating, away_rating, historical_context, outcome in precomputed:
            base_probs = calculate_match_probabilities(home_rating, away_rating)
            probs = calibrate_probabilities_with_history(base_probs, historical_context, weight_scale=1.5)
            total_brier += _brier_score(probs, outcome)
        baseline_brier = total_brier / len(precomputed)

    return {
        "matches_available": len(completed),
        "min_matches_required": min_matches,
        "best": {
            **best_params,
            "avg_brier": round(best_avg_brier, 4) if best_avg_brier < 999.0 else None,
        } if best_params else None,
        "default": {
            "weight_scale": 1.5,
            "home_advantage": 0.0,
            "rho": DEFAULT_RHO,
            "avg_brier": round(baseline_brier, 4) if baseline_brier is not None else None,
        },
    }


# --- fit_league_model: continuous per-league fit of the goal curve, rho,
# and a recalibration temperature, walk-forward-disciplined via a
# chronological train/calibration/test split --------------------------------
#
# sweep_league_parameters above answers a narrower question (does trusting
# league history more or less, at a few coarse home_advantage/rho grid
# points, help the *history-calibrated* live-app model) with a fixed grid
# and no held-out evaluation. fit_league_model fits the parameters
# soccer_ratings.backtest.evaluate_match actually uses — the exponential
# goal curve, rho, and a post-hoc temperature — continuously rather than
# off a five-value rho grid, and reports Brier on a slice of matches none
# of the fitting ever saw, so "the fit helped" is a claim about
# generalization, not a claim about the very data it was fit to. See
# fit_league_model's docstring for why home_advantage itself isn't in that
# list — it's not an oversight.

DEFAULT_RHO_BOUNDS = (-0.35, 0.15)
DEFAULT_GOAL_RATE_BOUNDS = (80.0, 4000.0)
DEFAULT_TEMPERATURE_BOUNDS = (0.4, 2.5)

# Golden-section search shrinks the bracket by ~0.618x per iteration,
# so 16 iterations narrows any of the bounds above to well under 0.1% of
# their original width — far tighter than the data can actually resolve —
# while keeping each fit fast enough to run across every imported league
# in one background job.
_GOLDEN_SECTION_ITERATIONS = 16

_TRAIN_FRACTION = 0.70
_CALIBRATION_FRACTION = 0.15
# Below this many matches, a temperature fit is more likely to be chasing
# split-specific noise than a real residual bias; temperature is left at
# 1.0 (no-op) instead.
_MIN_CALIBRATION_MATCHES = 10

_GOLDEN_RATIO = (math.sqrt(5.0) - 1.0) / 2.0


def _golden_section_minimize(
    objective, lo: float, hi: float, *, iterations: int = _GOLDEN_SECTION_ITERATIONS
) -> float:
    """Minimize a scalar function assumed to be roughly unimodal on
    [lo, hi], without derivatives or external dependencies.

    Good enough for the objectives used here — Poisson negative
    log-likelihood in one curve parameter, Brier score in rho or
    home_advantage or temperature — which are smooth, single-basin
    functions of one variable over a bounded, physically sensible range.
    Not a general-purpose optimizer: it will settle on a local optimum for
    a genuinely multi-modal objective, which none of these are expected to
    be.
    """
    if hi <= lo:
        return lo

    a, b = float(lo), float(hi)
    c = b - _GOLDEN_RATIO * (b - a)
    d = a + _GOLDEN_RATIO * (b - a)
    fc, fd = objective(c), objective(d)

    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - _GOLDEN_RATIO * (b - a)
            fc = objective(c)
        else:
            a, c, fc = c, d, fd
            d = a + _GOLDEN_RATIO * (b - a)
            fd = objective(d)

    return (a + b) / 2.0


def _chronological_split(
    matches: list[dict],
    *,
    train_fraction: float = _TRAIN_FRACTION,
    calibration_fraction: float = _CALIBRATION_FRACTION,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split already-completed matches into train/calibration/test slices in
    date order — train fits the curve/rho/home_advantage, calibration fits
    temperature, and test is untouched by any fitting, used only to report
    how the fitted parameters do on matches they never influenced.
    """
    ordered = sort_matches_by_date(matches)
    total = len(ordered)
    train_end = min(total, round(total * train_fraction))
    calibration_end = min(total, train_end + round(total * calibration_fraction))
    return ordered[:train_end], ordered[train_end:calibration_end], ordered[calibration_end:]


def _default_goal_curve() -> dict[str, float]:
    return {
        "home_goal_scale": DEFAULT_HOME_GOAL_SCALE,
        "home_goal_rate": DEFAULT_HOME_GOAL_RATE,
        "away_goal_scale": DEFAULT_AWAY_GOAL_SCALE,
        "away_goal_rate": DEFAULT_AWAY_GOAL_RATE,
    }


def _fit_side_goal_curve(
    gaps: list[float],
    goals: list[int],
    *,
    fallback_scale: float,
    fallback_rate: float,
    rate_bounds: tuple[float, float] = DEFAULT_GOAL_RATE_BOUNDS,
    iterations: int = _GOLDEN_SECTION_ITERATIONS,
) -> tuple[float, float, float]:
    """Poisson maximum-likelihood fit of lambda = scale * exp(gap / rate)
    for one side (home or away — the caller negates gap for away, so this
    one function handles both directions of the same curve shape).

    For any fixed rate, the scale that maximizes Poisson log-likelihood has
    a closed form (sum(goals) / sum(exp(gap/rate)) — set the derivative of
    the log-likelihood with respect to scale to zero and solve), so only
    rate needs a numerical search; scale is recomputed exactly at each
    candidate rate golden-section tries.

    Returns (scale, rate, negative_log_likelihood) — the third value lets
    _fit_home_advantage_and_curve add the home and away fits' likelihoods
    together without re-scoring either side from scratch.
    """
    total_goals = float(sum(goals))
    if not gaps or total_goals <= 0:
        return fallback_scale, fallback_rate, float("inf")

    def negative_log_likelihood(rate: float) -> float:
        if rate <= 0:
            return float("inf")
        exp_terms = [math.exp(gap / rate) for gap in gaps]
        denominator = sum(exp_terms)
        if denominator <= 0:
            return float("inf")
        scale = total_goals / denominator
        nll = 0.0
        for exp_term, observed in zip(exp_terms, goals):
            lam = max(1e-9, scale * exp_term)
            nll += lam - observed * math.log(lam)
        return nll

    best_rate = _golden_section_minimize(
        negative_log_likelihood, rate_bounds[0], rate_bounds[1], iterations=iterations
    )
    exp_terms = [math.exp(gap / best_rate) for gap in gaps]
    denominator = sum(exp_terms)
    best_scale = total_goals / denominator if denominator > 0 else fallback_scale
    return best_scale, best_rate, negative_log_likelihood(best_rate)


def _fit_goal_curve_with_nll(
    matches: list[dict],
    *,
    home_advantage: float,
    rate_bounds: tuple[float, float] = DEFAULT_GOAL_RATE_BOUNDS,
    iterations: int = _GOLDEN_SECTION_ITERATIONS,
) -> tuple[dict[str, float], float]:
    """Fit all four goal-curve parameters against real scorelines for a
    candidate home_advantage, returning the fitted curve and the summed
    home+away Poisson negative log-likelihood at that fit — the objective
    _fit_home_advantage_and_curve searches over.

    Home and away lambdas share the same rating gap (shifted by
    home_advantage) but scale in opposite directions, so the away side
    reuses _fit_side_goal_curve on the negated gap rather than duplicating
    the fit.
    """
    home_gaps: list[float] = []
    home_goals: list[int] = []
    away_gaps: list[float] = []
    away_goals: list[int] = []

    for match in matches:
        home_rating = match.get("home_rating")
        away_rating = match.get("away_rating")
        goals_for = match.get("home_goals")
        goals_against = match.get("away_goals")
        if None in (home_rating, away_rating, goals_for, goals_against):
            continue
        gap = float(home_rating) - float(away_rating) + home_advantage
        home_gaps.append(gap)
        home_goals.append(int(goals_for))
        away_gaps.append(-gap)
        away_goals.append(int(goals_against))

    home_scale, home_rate, home_nll = _fit_side_goal_curve(
        home_gaps,
        home_goals,
        fallback_scale=DEFAULT_HOME_GOAL_SCALE,
        fallback_rate=DEFAULT_HOME_GOAL_RATE,
        rate_bounds=rate_bounds,
        iterations=iterations,
    )
    away_scale, away_rate, away_nll = _fit_side_goal_curve(
        away_gaps,
        away_goals,
        fallback_scale=DEFAULT_AWAY_GOAL_SCALE,
        fallback_rate=DEFAULT_AWAY_GOAL_RATE,
        rate_bounds=rate_bounds,
        iterations=iterations,
    )
    curve = {
        "home_goal_scale": home_scale,
        "home_goal_rate": home_rate,
        "away_goal_scale": away_scale,
        "away_goal_rate": away_rate,
    }
    return curve, home_nll + away_nll


def _fit_goal_curve(
    matches: list[dict],
    *,
    home_advantage: float,
    rate_bounds: tuple[float, float] = DEFAULT_GOAL_RATE_BOUNDS,
    iterations: int = _GOLDEN_SECTION_ITERATIONS,
) -> dict[str, float]:
    """Fit the goal curve for a *given* home_advantage — see
    _fit_goal_curve_with_nll for the scored version this wraps, used when
    only the fitted parameters are needed (e.g. re-deriving the curve for
    an already-chosen home_advantage).
    """
    curve, _ = _fit_goal_curve_with_nll(
        matches, home_advantage=home_advantage, rate_bounds=rate_bounds, iterations=iterations
    )
    return curve


def _brier_for_model_params(
    matches: list[dict],
    *,
    home_advantage: float,
    rho: float,
    curve: dict[str, float],
    temperature: float = DEFAULT_TEMPERATURE,
) -> float | None:
    """Average Brier score of the exact pipeline
    soccer_ratings.backtest.evaluate_match uses for its "raw model" —
    calculate_match_probabilities then apply_temperature, no market blend,
    no history calibration — under a candidate parameter set. This is the
    objective every fit in this module ultimately optimizes.
    """
    total = 0.0
    count = 0
    for match in matches:
        home_rating = match.get("home_rating")
        away_rating = match.get("away_rating")
        home_goals = match.get("home_goals")
        away_goals = match.get("away_goals")
        if None in (home_rating, away_rating, home_goals, away_goals):
            continue
        probabilities = calculate_match_probabilities(
            float(home_rating),
            float(away_rating),
            home_advantage=home_advantage,
            rho=rho,
            **curve,
        )
        probabilities = apply_temperature(probabilities, temperature)
        outcome = match_outcome(int(home_goals), int(away_goals))
        total += _brier_score(probabilities, outcome)
        count += 1
    return total / count if count else None


def _fit_rho(
    matches: list[dict],
    *,
    home_advantage: float,
    curve: dict[str, float],
    bounds: tuple[float, float] = DEFAULT_RHO_BOUNDS,
    iterations: int = _GOLDEN_SECTION_ITERATIONS,
) -> float:
    """rho only reshapes the four low-score cells of the score grid (see
    odds._dixon_coles_tau), so unlike the goal curve it has no Poisson
    closed form of its own — it's fit by golden-section search directly on
    Brier score, the same objective the rest of this module reports.
    """

    def objective(candidate_rho: float) -> float:
        brier = _brier_for_model_params(
            matches, home_advantage=home_advantage, rho=candidate_rho, curve=curve
        )
        return brier if brier is not None else float("inf")

    return _golden_section_minimize(objective, bounds[0], bounds[1], iterations=iterations)


def fit_league_model(
    matches: list[dict],
    *,
    min_matches: int = DEFAULT_MIN_MATCHES,
    rho_bounds: tuple[float, float] = DEFAULT_RHO_BOUNDS,
    goal_rate_bounds: tuple[float, float] = DEFAULT_GOAL_RATE_BOUNDS,
    temperature_bounds: tuple[float, float] = DEFAULT_TEMPERATURE_BOUNDS,
) -> dict:
    """Fit the four goal-curve parameters and rho on a training slice, fit
    a recalibration temperature on a following calibration slice, and
    report Brier on a final test slice none of the fitting ever saw — the
    train/calibration/test split soccer_ratings.backtest itself cannot
    provide, since it exists to grade a model against history it wasn't
    fit on, not to do the fitting.

    home_advantage is deliberately *not* fit here, and always comes back
    0.0. This isn't an omission: in calculate_match_probabilities,
    home_advantage only ever appears as an additive shift folded into the
    same "gap" that feeds both home_goal_scale*exp(gap/rate) and
    away_goal_scale*exp(-gap/rate) — and once scale and rate are both free
    per side (which fitting the curve requires), that shift is exactly,
    algebraically absorbable into home_goal_scale and away_goal_scale.
    "Exactly" isn't a figure of speech: the Poisson log-likelihood of the
    training goals is provably identical for every home_advantage once the
    curve is refit at each one — verified against a synthetic league with a
    known home_advantage, where the fitted goals log-likelihood came back
    bit-for-bit equal from 0 all the way to the search bound, and the
    "best" home_advantage golden-section returned was arbitrary noise
    depending on where the search happened to bracket, not a real fit. A
    downstream Brier objective doesn't rescue it either: holding a curve
    fixed and searching home_advantage on top just reproduces whatever
    home_advantage the curve was fit at in the first place, because
    shifting home_advantage while leaving the curve fixed is (to first
    order) the same reparameterization the curve fit already explored.
    home_advantage and the curve's home/away scale asymmetry are the same
    degree of freedom in this model, not two.

    The curve fit already delivers what a per-league home_advantage was
    meant to: home_goal_scale/away_goal_scale, fit fresh per league,
    *is* a continuous, per-league measure of home advantage — expressed as
    a goal-scoring asymmetry rather than a single rating-point constant,
    which is a strictly richer representation (see the ratio between the
    two climb with a league's true home-field strength in the identity
    check this design replaced). tuning_params["home_advantage"] is kept
    in the schema and still respected by evaluate_match and
    compare_teams_from_ratings as a manual override for anyone who wants
    to layer an explicit further nudge on top — fit_league_model simply
    doesn't try to compute one automatically, because there is no
    identifiable value to compute.

    rho is fit afterward, by Brier score rather than Poisson likelihood:
    unlike home_advantage, it only reshapes the four low-score cells of
    the discrete outcome distribution (see odds._dixon_coles_tau) and
    doesn't share a degree of freedom with the goal curve, so it has no
    equivalent identifiability problem.

    Returns "fitted": None if there isn't enough history to trust a fit
    (below min_matches, same guard sweep_league_parameters uses); otherwise
    the fitted parameters, ready to hand to
    soccer_ratings.db.update_league_tuning_parameters, plus "validation":
    out-of-sample Brier for the fit against the module defaults, or None if
    the split left no test matches at all.
    """
    completed = [
        match
        for match in matches
        if match.get("home_goals") is not None
        and match.get("away_goals") is not None
        and match.get("home_rating") is not None
        and match.get("away_rating") is not None
    ]
    unavailable = {
        "matches_available": len(completed),
        "min_matches_required": min_matches,
        "train_matches": 0,
        "calibration_matches": 0,
        "test_matches": 0,
        "train_avg_brier": None,
        "fitted": None,
        "validation": None,
    }
    if len(completed) < min_matches:
        return unavailable

    train, calibration, test = _chronological_split(completed)
    if len(train) < min_matches:
        return unavailable

    best_home_advantage = 0.0
    best_curve = _fit_goal_curve(train, home_advantage=best_home_advantage, rate_bounds=goal_rate_bounds)
    best_rho = _fit_rho(train, home_advantage=best_home_advantage, curve=best_curve, bounds=rho_bounds)
    train_brier = _brier_for_model_params(
        train, home_advantage=best_home_advantage, rho=best_rho, curve=best_curve
    )

    temperature = DEFAULT_TEMPERATURE
    if len(calibration) >= _MIN_CALIBRATION_MATCHES:

        def temperature_objective(candidate_temperature: float) -> float:
            brier = _brier_for_model_params(
                calibration,
                home_advantage=best_home_advantage,
                rho=best_rho,
                curve=best_curve,
                temperature=candidate_temperature,
            )
            return brier if brier is not None else float("inf")

        temperature = _golden_section_minimize(
            temperature_objective, temperature_bounds[0], temperature_bounds[1]
        )

    fitted = {
        "home_advantage": round(best_home_advantage, 2),
        "rho": round(best_rho, 4),
        "temperature": round(temperature, 4),
        **{key: round(value, 4) for key, value in best_curve.items()},
    }

    validation = None
    if test:
        fitted_test_brier = _brier_for_model_params(
            test, home_advantage=best_home_advantage, rho=best_rho, curve=best_curve, temperature=temperature
        )
        default_test_brier = _brier_for_model_params(
            test, home_advantage=0.0, rho=DEFAULT_RHO, curve=_default_goal_curve()
        )
        improvement = None
        if fitted_test_brier is not None and default_test_brier is not None:
            improvement = round(default_test_brier - fitted_test_brier, 4)
        validation = {
            "test_matches": len(test),
            "fitted_avg_brier": round(fitted_test_brier, 4) if fitted_test_brier is not None else None,
            "default_avg_brier": round(default_test_brier, 4) if default_test_brier is not None else None,
            "improvement": improvement,
        }

    return {
        "matches_available": len(completed),
        "min_matches_required": min_matches,
        "train_matches": len(train),
        "calibration_matches": len(calibration),
        "test_matches": len(test),
        "train_avg_brier": round(train_brier, 4) if train_brier is not None else None,
        "fitted": fitted,
        "validation": validation,
    }
