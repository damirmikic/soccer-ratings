from __future__ import annotations


def _date_sort_key(value) -> str:
    """Rearrange a dd.mm.yy date so string ordering matches chronology."""
    text = str(value or "").strip()
    parts = text.split(".")
    if len(parts) == 3:
        day, month, year = parts
        return f"{year}.{month}.{day}"
    return text


def _sorted_by_date_desc(matches: list[dict]) -> list[dict]:
    return sorted(matches, key=lambda match: _date_sort_key(match.get("date")), reverse=True)


def build_head_to_head(
    historical_matches: list[dict],
    home_team: str,
    away_team: str,
    limit: int = 10,
) -> dict | None:
    """Previous meetings between two teams (either venue), most recent
    first, plus the W/D/L record and average goals from home_team's
    perspective. Draws entirely from already-loaded league history — no
    extra query or scrape.
    """
    normalized_home = home_team.strip().casefold()
    normalized_away = away_team.strip().casefold()

    pairing_matches = [
        match
        for match in historical_matches
        if {
            str(match.get("home_team", "")).strip().casefold(),
            str(match.get("away_team", "")).strip().casefold(),
        }
        == {normalized_home, normalized_away}
    ]
    if not pairing_matches:
        return None

    recent = _sorted_by_date_desc(pairing_matches)[:limit]

    wins = draws = losses = 0
    goals_for = goals_against = 0
    scored_matches = 0
    for match in recent:
        home_goals = match.get("home_goals")
        away_goals = match.get("away_goals")
        if home_goals is None or away_goals is None:
            continue
        scored_matches += 1

        match_home = str(match.get("home_team", "")).strip().casefold()
        if match_home == normalized_home:
            team_goals, opponent_goals = home_goals, away_goals
        else:
            team_goals, opponent_goals = away_goals, home_goals

        goals_for += team_goals
        goals_against += opponent_goals
        if team_goals > opponent_goals:
            wins += 1
        elif team_goals < opponent_goals:
            losses += 1
        else:
            draws += 1

    return {
        "matches": recent,
        "sample_size": len(recent),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "avg_goals_for": round(goals_for / scored_matches, 2) if scored_matches else 0.0,
        "avg_goals_against": round(goals_against / scored_matches, 2) if scored_matches else 0.0,
    }


def build_form_guide(
    historical_matches: list[dict],
    team_name: str,
    limit: int = 5,
) -> dict | None:
    """A team's last `limit` completed matches against any opponent, most
    recent first, with a W/D/L strip and goals for/against. Also draws
    entirely from already-loaded league history.
    """
    normalized_team = team_name.strip().casefold()

    team_matches = [
        match
        for match in historical_matches
        if match.get("home_goals") is not None
        and match.get("away_goals") is not None
        and (
            str(match.get("home_team", "")).strip().casefold() == normalized_team
            or str(match.get("away_team", "")).strip().casefold() == normalized_team
        )
    ]
    if not team_matches:
        return None

    recent = _sorted_by_date_desc(team_matches)[:limit]

    entries = []
    wins = draws = losses = 0
    goals_for = goals_against = 0
    for match in recent:
        is_home = str(match.get("home_team", "")).strip().casefold() == normalized_team
        team_goals = match["home_goals"] if is_home else match["away_goals"]
        opponent_goals = match["away_goals"] if is_home else match["home_goals"]
        opponent = match.get("away_team") if is_home else match.get("home_team")

        goals_for += team_goals
        goals_against += opponent_goals
        if team_goals > opponent_goals:
            result = "W"
            wins += 1
        elif team_goals < opponent_goals:
            result = "L"
            losses += 1
        else:
            result = "D"
            draws += 1

        entries.append(
            {
                "date": match.get("date"),
                "opponent": opponent,
                "venue": "H" if is_home else "A",
                "goals_for": team_goals,
                "goals_against": opponent_goals,
                "result": result,
            }
        )

    sample_size = len(entries)
    return {
        "matches": entries,
        "sample_size": sample_size,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_goals_for": round(goals_for / sample_size, 2) if sample_size else 0.0,
        "avg_goals_against": round(goals_against / sample_size, 2) if sample_size else 0.0,
        "form_string": "".join(entry["result"] for entry in entries),
    }
