from __future__ import annotations

from dataclasses import asdict, dataclass
from html.parser import HTMLParser


@dataclass
class CountryRating:
    rank: int
    country: str
    rating: float
    country_path: str | None = None
    continent: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LeagueSummary:
    rank: int
    league: str
    rating: float
    league_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TeamRating:
    rank: int
    team: str
    rating: float
    team_path: str | None = None
    mode: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpecialRatingLinks:
    general: str | None = None
    home: str | None = None
    away: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedRow:
    texts: list[str]
    hrefs: list[str]


@dataclass
class TeamHistoryMatch:
    sequence: int | None
    date: str
    competition: str
    home_team: str
    away_team: str
    home_odds: float
    draw_odds: float
    away_odds: float
    home_rating: float
    away_rating: float
    home_goals: int | None = None
    away_goals: int | None = None
    result: str | None = None
    focal_team: str | None = None
    source_team_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ContentTableHTMLParser(HTMLParser):
    """Collect row text and anchor hrefs from target content tables."""

    def __init__(self) -> None:
        super().__init__()
        self._in_target_div = False
        self._target_div_depth = 0
        self._table_depth = 0
        self._in_row = False
        self._current_cell_parts: list[str] = []
        self._current_cells: list[str] = []
        self._current_hrefs: list[str] = []
        self.rows: list[ParsedRow] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)

        if tag == "div" and self._is_target_div(attrs_dict):
            self._in_target_div = True
            self._target_div_depth = 1
            return

        if self._in_target_div and tag == "div":
            self._target_div_depth += 1

        if not self._in_target_div:
            return

        if tag == "table":
            self._table_depth += 1
            return

        if self._table_depth == 0:
            return

        if tag == "tr":
            self._in_row = True
            self._current_cells = []
            self._current_cell_parts = []
            self._current_hrefs = []
            return

        if not self._in_row:
            return

        if tag in {"td", "th"}:
            self._current_cell_parts = []
            return

        if tag == "a":
            href = attrs_dict.get("href")
            if href:
                self._current_hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if self._in_target_div and tag == "div":
            self._target_div_depth -= 1
            if self._target_div_depth == 0:
                self._in_target_div = False
            return

        if not self._in_target_div:
            return

        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1
            return

        if not self._in_row:
            return

        if tag in {"td", "th"}:
            self._current_cells.append(" ".join(self._current_cell_parts).strip())
            self._current_cell_parts = []
            return

        if tag == "tr":
            if any(text for text in self._current_cells):
                self.rows.append(
                    ParsedRow(texts=self._current_cells.copy(), hrefs=self._current_hrefs.copy())
                )
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if not self._in_target_div or not self._in_row:
            return

        text = data.strip()
        if text:
            self._current_cell_parts.append(text)

    @staticmethod
    def _is_target_div(attrs: dict[str, str | None]) -> bool:
        class_attr = attrs.get("class", "")
        style_attr = attrs.get("style", "")
        class_tokens = set(class_attr.split())
        return "content2" in class_tokens and "border:0px solid" in style_attr


def _parse_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").strip())
    except ValueError:
        return None


def _parse_rank(value: str) -> int | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _parse_rows(html: str) -> list[ParsedRow]:
    parser = ContentTableHTMLParser()
    parser.feed(html)
    return parser.rows


def parse_rankings(html: str, continent: str | None = None) -> list[CountryRating]:
    rankings: list[CountryRating] = []
    for row in _parse_rows(html):
        if len(row.texts) != 2 or len(row.hrefs) != 1:
            continue

        rating = _parse_float(row.texts[1])
        if rating is None:
            continue

        rankings.append(
            CountryRating(
                rank=len(rankings) + 1,
                country=row.texts[0],
                rating=rating,
                country_path=row.hrefs[0],
                continent=continent,
            )
        )
    return rankings


def parse_leagues(html: str) -> list[LeagueSummary]:
    leagues: list[LeagueSummary] = []
    for row in _parse_rows(html):
        if len(row.texts) != 4 or not row.hrefs:
            continue

        rank = _parse_rank(row.texts[0])
        rating = _parse_float(row.texts[3])
        if rank is None or rating is None:
            continue

        leagues.append(
            LeagueSummary(
                rank=rank,
                league=row.texts[1],
                rating=rating,
                league_path=row.hrefs[0],
            )
        )
    return leagues


def parse_team_ratings(html: str, mode: str | None = None) -> list[TeamRating]:
    teams: list[TeamRating] = []
    for row in _parse_rows(html):
        if len(row.texts) < 5 or not row.hrefs:
            continue

        rank = _parse_rank(row.texts[0])
        rating = _parse_float(row.texts[-1])
        if rank is None or rating is None:
            continue

        teams.append(
            TeamRating(
                rank=rank,
                team=row.texts[1],
                rating=rating,
                team_path=row.hrefs[0],
                mode=mode,
            )
        )
    return teams


def parse_special_rating_links(html: str) -> SpecialRatingLinks:
    links = SpecialRatingLinks()
    for row in _parse_rows(html):
        if len(row.texts) != 1 or len(row.hrefs) != 1:
            continue

        label = row.texts[0].strip().lower()
        href = row.hrefs[0]
        if label == "home ratings":
            links.home = href
        elif label == "away ratings":
            links.away = href
        elif label == "general ratings":
            links.general = href

    return links


def parse_team_history_matches(
    html: str,
    focal_team: str | None = None,
    source_team_path: str | None = None,
) -> list[TeamHistoryMatch]:
    rows = _parse_rows(html)
    inferred_focal_team = focal_team or _infer_focal_team(rows)
    matches: list[TeamHistoryMatch] = []

    for row in rows:
        match = _parse_team_history_row(
            row,
            focal_team=inferred_focal_team,
            source_team_path=source_team_path,
        )
        if match is not None:
            matches.append(match)

    return matches


def _infer_focal_team(rows: list[ParsedRow]) -> str | None:
    for row in rows:
        if "Matches" in row.texts and len(row.texts) >= 2:
            for text in row.texts:
                if not text:
                    continue
                if text != "Matches" and text not in {"1", "X", "2", "Odds", "Home/Away", "Res."}:
                    return text
    return None


def _parse_team_history_row(
    row: ParsedRow,
    focal_team: str | None,
    source_team_path: str | None,
) -> TeamHistoryMatch | None:
    if len(row.texts) < 10:
        return None

    date_text = row.texts[1].strip()
    if not _looks_like_date(date_text):
        return None

    match_text = row.texts[2].strip()
    if " - " not in match_text:
        return None

    home_odds = _parse_float(row.texts[3])
    draw_odds = _parse_float(row.texts[4])
    away_odds = _parse_float(row.texts[5])
    competition = row.texts[7].strip()
    home_rating = _parse_float(row.texts[8])
    away_rating = _parse_float(row.texts[9])
    if None in {home_odds, draw_odds, away_odds, home_rating, away_rating}:
        return None

    home_team, away_team = [_clean_team_name(part) for part in match_text.split(" - ", 1)]
    result_text = row.texts[10].strip() if len(row.texts) > 10 else ""
    home_goals, away_goals = _parse_score(result_text)

    return TeamHistoryMatch(
        sequence=_parse_rank(row.texts[0]),
        date=date_text[:8],
        competition=competition,
        home_team=home_team,
        away_team=away_team,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        home_rating=home_rating,
        away_rating=away_rating,
        home_goals=home_goals,
        away_goals=away_goals,
        result=result_text or None,
        focal_team=focal_team,
        source_team_path=source_team_path,
    )


def _looks_like_date(value: str) -> bool:
    return len(value) >= 8 and value[2] == "." and value[5] == "."


def _parse_score(value: str) -> tuple[int | None, int | None]:
    if ":" not in value:
        return None, None
    left, right = value.split(":", 1)
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None, None


def _clean_team_name(value: str) -> str:
    return (
        value.replace("↓", "")
        .replace("↑", "")
        .replace("*", "")
        .strip()
    )
