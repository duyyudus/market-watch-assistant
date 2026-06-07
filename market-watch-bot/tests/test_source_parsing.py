from __future__ import annotations

from common.source_parsing import parse_source_items, parse_source_items_async

GOOGLE_RSS_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Oil rises - Publisher</title>
      <link>https://news.google.com/rss/articles/encoded?oc=5</link>
      <description>
        Crude climbs as traders weigh supply risks. Futures rose in early trading.
      </description>
      <guid>item-1</guid>
    </item>
  </channel>
</rss>
"""


def test_parse_google_rss_items_preserves_google_url_and_metadata() -> None:
    items = parse_source_items(GOOGLE_RSS_BODY, source_type="google-rss")

    assert len(items) == 1
    item = items[0]
    assert item.title == "Oil rises - Publisher"
    assert item.url == "https://news.google.com/rss/articles/encoded?oc=5"
    assert item.description == (
        "Crude climbs as traders weigh supply risks. Futures rose in early trading."
    )
    assert item.guid == "item-1"
    assert item.raw_payload["google_news_url"] == item.url
    assert "google_news_decoded_url" not in item.raw_payload
    assert "google_news_decode_status" not in item.raw_payload


def test_parse_google_rss_items_has_no_decode_metadata() -> None:
    items = parse_source_items(GOOGLE_RSS_BODY, source_type="google-rss")

    assert items[0].url == "https://news.google.com/rss/articles/encoded?oc=5"
    assert not any(key.startswith("google_news_decode") for key in items[0].raw_payload)


def test_parse_google_rss_items_clears_single_sentence_description() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Oil rises - Publisher</title>
      <link>https://news.google.com/rss/articles/encoded?oc=5</link>
      <description>Crude climbs.</description>
      <guid>item-1</guid>
    </item>
  </channel>
</rss>
"""

    items = parse_source_items(body, source_type="google-rss")

    assert items[0].description == ""


def test_parse_google_rss_items_clears_description_when_it_repeats_title() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Oil rises - Publisher</title>
      <link>https://news.google.com/rss/articles/encoded?oc=5</link>
      <description>Oil rises - Publisher</description>
      <guid>item-1</guid>
    </item>
  </channel>
</rss>
"""

    items = parse_source_items(body, source_type="google-rss")

    assert items[0].description == ""


def test_parse_google_rss_items_clears_description_when_only_separator_differs() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Politicians and the bond markets: lost in translation - Financial Times</title>
      <link>https://news.google.com/rss/articles/encoded?oc=5</link>
      <description>
        Politicians and the bond markets: lost in translation Financial Times
      </description>
      <guid>item-1</guid>
    </item>
  </channel>
</rss>
"""

    items = parse_source_items(body, source_type="google-rss")

    assert items[0].description == ""


async def test_parse_google_rss_items_async_does_not_call_decoder() -> None:
    items = await parse_source_items_async(
        GOOGLE_RSS_BODY,
        source_type="google-rss",
    )

    assert items[0].raw_payload["google_news_url"] == items[0].url
