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


def test_parse_rss_items_handles_mislabeled_utf16_declaration() -> None:
    fixture = RSS_FIXTURE.replace('encoding="UTF-8"', 'encoding="utf-16"')

    items = parse_rss_items(fixture)

    assert len(items) == 1
    assert items[0].title == "Oil jumps on shipping disruption"


def test_parse_rss_items_cleans_escaped_html_and_entities() -> None:
    description = (
        '&lt;a href="https://example.com/euro"&gt;'
        '&lt;img src="https://cdn.example.com/a.jpg" /&gt;&lt;/a&gt;'
        "Tỷ giá euro sáng ngày 5/6 đã nhích lên tại nhiều ngân hàng."
    )
    fixture = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Publisher Feed</title>
    <item>
      <title>Tỷ gi&amp;#225; euro ng&amp;#224;y 5/6</title>
      <link>https://example.com/euro</link>
      <description>{description}</description>
      <guid>euro-1</guid>
    </item>
  </channel>
</rss>
"""

    items = parse_rss_items(fixture)

    assert len(items) == 1
    assert items[0].title == "Tỷ giá euro ngày 5/6"
    assert items[0].description == "Tỷ giá euro sáng ngày 5/6 đã nhích lên tại nhiều ngân hàng."


def test_parse_rss_items_ignores_empty_dc_description() -> None:
    fixture = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
  <channel>
    <title>CoinDesk Feed</title>
    <item>
      <title>Bitcoin routines</title>
      <link>https://example.com/btc</link>
      <description>Bitcoin price recovers after correction.</description>
      <dc:description/>
      <guid>btc-1</guid>
    </item>
    <item>
      <title>Ethereum routines</title>
      <link>https://example.com/eth</link>
      <description>Ethereum gas fees drop.</description>
      <dc:description></dc:description>
      <guid>eth-1</guid>
    </item>
  </channel>
</rss>
"""
    items = parse_rss_items(fixture)

    assert len(items) == 2
    assert items[0].title == "Bitcoin routines"
    assert items[0].description == "Bitcoin price recovers after correction."
    assert items[1].title == "Ethereum routines"
    assert items[1].description == "Ethereum gas fees drop."
