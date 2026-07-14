from __future__ import annotations

from xml.sax.saxutils import escape


def build_sitemap_xml(urls: list[str]) -> str:
    entries = "".join(f"<url><loc>{escape(url)}</loc></url>" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}"
        "</urlset>"
    )
