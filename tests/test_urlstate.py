import unittest

from soccer_ratings.urlstate import build_share_url


class BuildShareUrlTests(unittest.TestCase):
    def test_no_params_returns_root(self) -> None:
        self.assertEqual(build_share_url(), "/")

    def test_empty_and_none_values_are_dropped(self) -> None:
        self.assertEqual(build_share_url(continent="", country=None), "/")

    def test_zero_margin_is_dropped(self) -> None:
        url = build_share_url(league="/England/Premier-League/", margin=0.0)
        self.assertEqual(url, "/?league=%2FEngland%2FPremier-League%2F")

    def test_nonzero_margin_is_kept(self) -> None:
        url = build_share_url(league="/England/Premier-League/", margin=2.5)
        self.assertIn("margin=2.5", url)

    def test_params_are_ordered_and_encoded(self) -> None:
        url = build_share_url(
            away="Chelsea",
            home="Arsenal",
            league="/England/Premier-League/",
            country="/England/",
            continent="Europe",
        )
        self.assertEqual(
            url,
            "/?continent=Europe&country=%2FEngland%2F&league=%2FEngland%2FPremier-League%2F"
            "&home=Arsenal&away=Chelsea",
        )


if __name__ == "__main__":
    unittest.main()
