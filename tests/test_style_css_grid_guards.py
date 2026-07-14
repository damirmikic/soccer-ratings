import re
import unittest
from pathlib import Path

STYLE_CSS_PATH = Path(__file__).resolve().parent.parent / "soccer_ratings" / "static" / "style.css"


def _rule_body(css: str, selector: str) -> str:
    """selector is the bare selector text, e.g. ".matchup-body" (no brace)."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"selector {selector!r} not found in style.css"
    return match.group(1)


class MatchCardGridShrinkGuardTests(unittest.TestCase):
    """A bare `1fr` grid track won't shrink below its content's intrinsic
    width (the default `min-width: auto` on grid items), so the wide
    multi-market odds row in .match-card forced these ancestors — and the
    whole page — wider than the viewport on narrow screens instead of
    scrolling internally via .match-card-odds's overflow-x. Confirmed with
    a real browser (Playwright) before and after the fix. These are
    grep-style guards against re-introducing the bare 1fr, since a layout
    overflow bug like this isn't visible to Python's TestClient (no real
    CSS layout engine)."""

    def setUp(self) -> None:
        self.css = STYLE_CSS_PATH.read_text(encoding="utf-8")

    def test_matchup_body_column_can_shrink(self) -> None:
        body = _rule_body(self.css, ".matchup-body")
        self.assertIn("minmax(0, 1fr)", body)

    def test_market_groups_column_can_shrink(self) -> None:
        body = _rule_body(self.css, ".market-groups")
        self.assertIn("minmax(0, 1fr)", body)

    def test_match_card_allows_shrinking_as_a_grid_item(self) -> None:
        body = _rule_body(self.css, ".match-card")
        self.assertIn("min-width: 0", body)

    def test_match_card_odds_scrolls_instead_of_wrapping(self) -> None:
        body = _rule_body(self.css, ".match-card-odds")
        self.assertIn("overflow-x: auto", body)


if __name__ == "__main__":
    unittest.main()
