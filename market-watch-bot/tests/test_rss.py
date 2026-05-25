from bot_worker.rss import parse_rss_items

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Market Feed</title>
    <item>
      <title>Oil jumps on shipping disruption</title>
      <link>https://example.com/oil?utm_source=rss</link>
      <description>Brent rises after a tanker incident.</description>
      <pubDate>Mon, 25 May 2026 03:00:00 GMT</pubDate>
      <guid>oil-1</guid>
    </item>
  </channel>
</rss>
"""


def test_parse_rss_items_extracts_feed_entries() -> None:
    items = parse_rss_items(RSS_FIXTURE)

    assert len(items) == 1
    assert items[0].title == "Oil jumps on shipping disruption"
    assert items[0].url == "https://example.com/oil?utm_source=rss"
    assert items[0].description == "Brent rises after a tanker incident."
    assert items[0].guid == "oil-1"
