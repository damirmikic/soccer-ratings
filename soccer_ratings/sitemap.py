import datetime
from xml.sax.saxutils import escape


def build_sitemap_xml(entries_data: list[dict | str]) -> str:
    xml_parts = []
    for item in entries_data:
        if isinstance(item, str):
            loc = item
            lastmod = None
            changefreq = None
            priority = None
        else:
            loc = item.get("loc", "")
            lastmod = item.get("lastmod")
            changefreq = item.get("changefreq")
            priority = item.get("priority")

        parts = [f"<loc>{escape(loc)}</loc>"]
        if lastmod:
            if isinstance(lastmod, (datetime.datetime, datetime.date)):
                lastmod_str = lastmod.strftime("%Y-%m-%d")
            else:
                lastmod_str = str(lastmod)
            parts.append(f"<lastmod>{escape(lastmod_str)}</lastmod>")

        if changefreq:
            parts.append(f"<changefreq>{escape(str(changefreq))}</changefreq>")

        if priority is not None:
            parts.append(f"<priority>{escape(str(priority))}</priority>")

        xml_parts.append("<url>" + "".join(parts) + "</url>")

    entries = "".join(xml_parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}"
        "</urlset>"
    )

