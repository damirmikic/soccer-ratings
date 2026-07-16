import unittest

from soccer_ratings.sitemap import build_sitemap_xml


class BuildSitemapXmlTests(unittest.TestCase):
    def test_empty_list_produces_empty_urlset(self) -> None:
        xml = build_sitemap_xml([])
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', xml)
        self.assertIn(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>', xml
        )

    def test_each_url_gets_its_own_loc_entry(self) -> None:
        xml = build_sitemap_xml(["https://ratings1x2.com/", "https://ratings1x2.com/?country=/England/"])
        self.assertIn("<url><loc>https://ratings1x2.com/</loc></url>", xml)
        self.assertIn(
            "<url><loc>https://ratings1x2.com/?country=/England/</loc></url>", xml
        )

    def test_special_characters_are_escaped(self) -> None:
        xml = build_sitemap_xml(["https://ratings1x2.com/?country=/England/&league=/England/Premier-League/"])
        self.assertIn("&amp;league=", xml)
        self.assertNotIn("&league=", xml)

    def test_dict_entry_includes_lastmod_changefreq_priority(self) -> None:
        import datetime
        dt = datetime.datetime(2026, 7, 16, 12, 0, 0)
        xml = build_sitemap_xml([
            {
                "loc": "https://ratings1x2.com/england",
                "lastmod": dt,
                "changefreq": "weekly",
                "priority": 0.8,
            }
        ])
        self.assertIn("<loc>https://ratings1x2.com/england</loc>", xml)
        self.assertIn("<lastmod>2026-07-16</lastmod>", xml)
        self.assertIn("<changefreq>weekly</changefreq>", xml)
        self.assertIn("<priority>0.8</priority>", xml)


if __name__ == "__main__":
    unittest.main()

