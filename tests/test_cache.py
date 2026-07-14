import unittest
from unittest import mock

from soccer_ratings.cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def test_returns_none_when_key_missing(self) -> None:
        cache = TTLCache(ttl_seconds=60)
        self.assertIsNone(cache.get("k"))

    def test_returns_cached_value_before_expiry(self) -> None:
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", "v")
        self.assertEqual(cache.get("k"), "v")

    @mock.patch("soccer_ratings.cache.time.monotonic")
    def test_expires_after_ttl(self, mock_monotonic) -> None:
        mock_monotonic.return_value = 1_000.0
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", "v")

        mock_monotonic.return_value = 1_000.0 + 61
        self.assertIsNone(cache.get("k"))

    @mock.patch("soccer_ratings.cache.time.monotonic")
    def test_still_fresh_just_before_ttl(self, mock_monotonic) -> None:
        mock_monotonic.return_value = 1_000.0
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", "v")

        mock_monotonic.return_value = 1_000.0 + 59
        self.assertEqual(cache.get("k"), "v")

    @mock.patch("soccer_ratings.cache.time.monotonic")
    def test_keys_are_independent(self, mock_monotonic) -> None:
        mock_monotonic.return_value = 1_000.0
        cache = TTLCache(ttl_seconds=60)
        cache.set("a", "va")

        mock_monotonic.return_value = 1_030.0
        cache.set("b", "vb")

        mock_monotonic.return_value = 1_061.0
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), "vb")


if __name__ == "__main__":
    unittest.main()
