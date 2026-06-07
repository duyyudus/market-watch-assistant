from __future__ import annotations

import httpx
import pytest

from common.article_fallbacks import first_article_fallback_text
from common.article_text import extract_article_text
from common.source_preview import preview_article_url, preview_source_url


class FakeAsyncClient:
    response: httpx.Response
    responses: dict[str, httpx.Response] = {}
    requests: list[tuple[str, dict[str, str]]] = []

    def __init__(self, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        return None

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        headers = kwargs.get("headers") or {}
        self.requests.append((url, dict(headers)))
        if self.responses:
            return self.responses[url]
        return self.response


def test_first_article_fallback_text_uses_first_non_empty_candidate() -> None:
    assert (
        first_article_fallback_text(None, "", "  Feed summary  ", "Title")
        == "Feed summary"
    )
    assert first_article_fallback_text(None, " ", "Title") == "Title"
    assert first_article_fallback_text(None, "", " ") == ""


@pytest.mark.asyncio
async def test_preview_source_url_parses_rss_items(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.requests = []
    FakeAsyncClient.response = httpx.Response(
        200,
        text="""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Oil jumps on shipping disruption</title>
          <link>https://example.com/oil</link>
          <description>Brent rises after a tanker incident.</description>
          <guid>oil-1</guid>
        </item></channel></rss>""",
        request=httpx.Request("GET", "https://example.com/feed.xml"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url="https://example.com/feed.xml",
        source_type="rss",
        limit=10,
    )

    assert result.status == "success"
    assert result.http_status == 200
    assert result.item_count == 1
    assert result.items[0].title == "Oil jumps on shipping disruption"
    assert result.items[0].url == "https://example.com/oil"
    assert FakeAsyncClient.requests[0][1]["User-Agent"].startswith("market-watch-assistant/")


@pytest.mark.asyncio
async def test_preview_source_url_keeps_google_rss_item_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    google_url = "https://news.google.com/rss/articles/abc?oc=5"
    FakeAsyncClient.response = httpx.Response(
        200,
        text=f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Oil jumps - Publisher</title>
          <link>{google_url}</link>
          <description>Brent rises after a tanker incident.</description>
          <guid>oil-1</guid>
        </item></channel></rss>""",
        request=httpx.Request("GET", "https://news.google.com/rss/search?q=oil"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url="https://news.google.com/rss/search?q=oil",
        source_type="google-rss",
        limit=10,
    )

    assert result.status == "success"
    assert result.items[0].title == "Oil jumps - Publisher"
    assert result.items[0].description == ""
    assert result.items[0].url == google_url


@pytest.mark.asyncio
async def test_preview_source_url_reports_blocked_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.response = httpx.Response(
        403,
        text="blocked",
        request=httpx.Request("GET", "https://example.com/feed.xml"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url="https://example.com/feed.xml",
        source_type="rss",
        limit=10,
    )

    assert result.status == "error"
    assert result.http_status == 403
    assert result.items == []
    assert "403" in (result.error_message or "")


@pytest.mark.asyncio
async def test_preview_article_url_extracts_and_caps_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.requests = []
    FakeAsyncClient.response = httpx.Response(
        200,
        text="<html><body><article>Readable article text from publisher</article></body></html>",
        request=httpx.Request("GET", "https://example.com/article"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_article_url(
        url="https://example.com/article",
        fallback_snippet=None,
        max_chars=16,
    )

    assert result.status == "success"
    assert result.text == "Readable article"
    assert result.truncated is True
    assert FakeAsyncClient.requests[0][1]["User-Agent"].startswith("market-watch-assistant/")


@pytest.mark.asyncio
async def test_preview_article_url_skips_google_rss_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.requests = []
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_article_url(
        url="https://news.google.com/rss/articles/encoded?oc=5",
        source_type="google-rss",
        fallback_snippet=None,
        fallback_title="Google RSS title",
        max_chars=20000,
    )

    assert result.status == "skipped"
    assert result.http_status is None
    assert result.text == ""
    assert result.text_length == 0
    assert result.error_message == "google_rss_feed_only"
    assert FakeAsyncClient.requests == []


@pytest.mark.asyncio
async def test_preview_article_url_uses_fallback_on_blocked_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.response = httpx.Response(
        403,
        text="blocked",
        request=httpx.Request("GET", "https://example.com/blocked"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_article_url(
        url="https://example.com/blocked",
        fallback_snippet="Feed summary is usable.",
        fallback_title="Oil supply shock analysis",
        max_chars=12,
    )

    assert result.status == "fallback"
    assert result.http_status == 403
    assert result.text == "Feed summary"
    assert result.text_length == len("Feed summary is usable.")
    assert result.truncated is True
    assert "403" in (result.error_message or "")


@pytest.mark.asyncio
async def test_preview_article_url_uses_title_fallback_on_blocked_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.response = httpx.Response(
        403,
        text="blocked",
        request=httpx.Request("GET", "https://example.com/blocked"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_article_url(
        url="https://example.com/blocked",
        fallback_snippet=None,
        fallback_title="Oil supply shock analysis",
        max_chars=20000,
    )

    assert result.status == "fallback"
    assert result.http_status == 403
    assert result.text == "Oil supply shock analysis"
    assert "403" in (result.error_message or "")


@pytest.mark.asyncio
async def test_preview_article_url_errors_without_fallback_on_blocked_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncClient.response = httpx.Response(
        403,
        text="blocked",
        request=httpx.Request("GET", "https://example.com/blocked"),
    )
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_article_url(
        url="https://example.com/blocked",
        fallback_snippet=None,
        fallback_title=None,
        max_chars=20000,
    )

    assert result.status == "error"
    assert result.http_status == 403
    assert result.text == ""
    assert "403" in (result.error_message or "")


def test_extract_article_text_strips_html() -> None:
    text = extract_article_text("<html><body><h1>Headline</h1><p>Body text</p></body></html>")

    assert text is not None
    assert "Body text" in text


def test_extract_article_text_removes_vietnambiz_vif_promo_box() -> None:
    html = """
    <html><body>
      <div class="article-body-content">
        <div class="vnbcbc-sapo" data-role="sapo">
          Chiều nay tại Singapore, Chứng khoán SSI và Virtu ghi nhận dấu mốc mới.
        </div>
        <div class="vnbcbc-body vceditor-content wi-active" data-role="content">
          <p>SSI hợp tác với Virtu vận hành mô hình Global Broker tại Việt Nam.</p>
          <p>Thị trường vốn Việt Nam đang từng bước tiệm cận thông lệ quốc tế.</p>
        </div>
        <div style="clear:both;">
          <div class="mceEditable VnBizPreviewMode align-center" data-type="boxcontent">
            <div class="mceEditable box-container box-vif">
              <p>Diễn đàn Đầu tư Việt Nam 2026 - Summer Summit</p>
              <p>Thời gian: 11/06/2026</p>
              <p>Vietnam Investment Forum 2026 - Summer Summit quy tụ đại diện cơ quan quản lý.</p>
              <p>Tham gia khảo sát "Dự báo của bạn về nửa cuối năm 2026".</p>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """

    text = extract_article_text(
        html,
        url="https://vietnambiz.vn/ssi-hop-tac-voi-virtu-202662191028833.htm",
    )

    assert text is not None
    assert "SSI hợp tác với Virtu" in text
    assert "thông lệ quốc tế" in text
    assert "Diễn đàn Đầu tư Việt Nam 2026" not in text
    assert "Vietnam Investment Forum 2026" not in text


def test_extract_article_text_removes_vneconomy_related_article_boilerplate() -> None:
    html = """
    <html><body>
      <article class="ct-edtior-web news-type1">
        <h1>Chính sách mới hỗ trợ doanh nghiệp xuất khẩu</h1>
        <div class="news-sapo">
          Các doanh nghiệp xuất khẩu được kỳ vọng hưởng lợi từ chính sách tín dụng mới.
        </div>
        <div class="detail__content">
          <p>Ngân hàng Nhà nước công bố gói tín dụng ưu đãi cho doanh nghiệp xuất khẩu.</p>
          <p>Chính sách tập trung vào nhóm ngành có đơn hàng phục hồi trong quý tới.</p>
        </div>
        <div class="list-detail-revert_item">
          <h3>Bảo vệ môi trường, ứng phó biến đổi khí hậu là cơ hội đổi mới mô hình tăng trưởng</h3>
          <p>Thứ trưởng Lê Công Thành cho rằng việc bảo vệ môi trường là nhiệm vụ lâu dài...</p>
        </div>
        <div class="box-keyword">
          <h3 class="title">Từ khóa:</h3>
          <a class="tag"><span>tín dụng xuất khẩu</span></a>
        </div>
      </article>
      <section class="mt-48 block-job-same">
        <div class="main-job-ndt">
          <h2>Đọc thêm</h2>
          <h3>Hawaii tìm đường thoát khỏi cái bóng dầu mỏ</h3>
          <p>Hawaii đang theo đuổi mục tiêu đầy tham vọng về năng lượng tái tạo...</p>
        </div>
      </section>
      <section class="news-general mt-48">
        <div class="zone--event">
          <h3 class="zone__title">Dòng sự kiện</h3>
          <h3 class="zone__title--sub">Bài viết mới nhất</h3>
          <p>VnEconomy cập nhật giá vàng trong nước và thế giới hôm nay.</p>
        </div>
      </section>
      <div class="chatbot-askonomy-ai">
        <h3>Askonomy AI</h3>
        <div class="item-highlight-ai_question">
          <p>Thuế đối ứng của Mỹ có ảnh hướng thế nào đến chứng khoán?</p>
        </div>
        <div class="highlight-ai_reply">
          <p>Chính sách thuế quan mới của Mỹ có tác động đáng kể đến kinh tế Việt Nam.</p>
        </div>
      </div>
    </body></html>
    """

    text = extract_article_text(html, url="https://vneconomy.vn/chinh-sach-moi.htm")

    assert text is not None
    assert "Ngân hàng Nhà nước công bố gói tín dụng" in text
    assert "nhóm ngành có đơn hàng phục hồi" in text
    assert "Bảo vệ môi trường" not in text
    assert "Từ khóa:" not in text
    assert "Đọc thêm" not in text
    assert "Hawaii tìm đường" not in text
    assert "Dòng sự kiện" not in text
    assert "Bài viết mới nhất" not in text
    assert "VnEconomy cập nhật giá vàng" not in text
    assert "Askonomy AI" not in text
    assert "Thuế đối ứng của Mỹ" not in text
    assert "Chính sách thuế quan mới của Mỹ" not in text


def test_extract_article_text_removes_generic_event_boilerplate_block() -> None:
    html = """
    <html><body><article>
      <p>VN-Index tăng khi nhóm ngân hàng thu hút dòng tiền.</p>
      <p>Thanh khoản thị trường cải thiện so với phiên trước.</p>
      <p>Diễn đàn Đầu tư Việt Nam 2027 - Spring Forum</p>
      <p>Thời gian: 11/06/2027</p>
      <p>Địa điểm: L7 West Lake Hanoi by Lotte Hotels.</p>
      <p>Ba phiên thảo luận chính:</p>
      <p>Phiên thảo luận 1: Vĩ mô Việt Nam trước các cú sốc.</p>
      <p>Tìm hiểu chương trình tại Vietnam Investment Forum.</p>
    </article></body></html>
    """

    text = extract_article_text(html, url="https://vietnambiz.vn/article.htm")

    assert text is not None
    assert "VN-Index tăng" in text
    assert "Thanh khoản thị trường" in text
    assert "Diễn đàn Đầu tư Việt Nam 2027" not in text
    assert "Phiên thảo luận 1" not in text


def test_extract_article_text_preserves_body_event_mention_when_footer_is_removed() -> None:
    html = """
    <html><body><article>
      <p>
        Analysts said Vietnam Investment Forum 2026 - Summer Summit may highlight
        market structure reforms relevant to securities companies.
      </p>
      <p>SSI shares advanced as investors assessed the policy outlook.</p>
      <p>Vietnam Investment Forum 2026 - Summer Summit</p>
      <p>Thời gian: 11/06/2026</p>
      <p>Địa điểm: L7 West Lake Hanoi by Lotte Hotels.</p>
      <p>Tham gia khảo sát "Dự báo của bạn về nửa cuối năm 2026".</p>
    </article></body></html>
    """

    text = extract_article_text(html, url="https://vietnambiz.vn/article.htm")

    assert text is not None
    assert "may highlight market structure reforms" in text
    assert "SSI shares advanced" in text
    assert "Tham gia khảo sát" not in text


def test_extract_article_text_does_not_apply_vietnambiz_promo_cleanup_globally() -> None:
    html = """
    <html><body><article>
      <p>VN-Index tăng khi nhóm ngân hàng thu hút dòng tiền.</p>
      <p>Thanh khoản thị trường cải thiện so với phiên trước.</p>
      <p>Diễn đàn Đầu tư Việt Nam 2027 - Spring Forum</p>
      <p>Thời gian: 11/06/2027</p>
      <p>Địa điểm: L7 West Lake Hanoi by Lotte Hotels.</p>
      <p>Tham gia khảo sát kỳ vọng thị trường.</p>
    </article></body></html>
    """

    text = extract_article_text(html, url="https://example.com/article.htm")

    assert text is not None
    assert "VN-Index tăng" in text
    assert "Diễn đàn Đầu tư Việt Nam 2027" in text
    assert "Tham gia khảo sát" in text


def test_extract_article_text_does_not_empty_short_promo_like_text() -> None:
    html = """
    <html><body><article>
      <p>Diễn đàn Đầu tư Việt Nam 2027 - Spring Forum</p>
      <p>Thời gian: 11/06/2027</p>
      <p>Địa điểm: L7 West Lake Hanoi by Lotte Hotels.</p>
      <p>Tham gia khảo sát kỳ vọng thị trường.</p>
    </article></body></html>
    """

    text = extract_article_text(html, url="https://vietnambiz.vn/article.htm")

    assert text is not None
    assert "Diễn đàn Đầu tư Việt Nam 2027" in text
    assert "Tham gia khảo sát" in text


@pytest.mark.asyncio
async def test_preview_source_url_crawls_section_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section_url = "https://example.com/markets/"
    article_url = "https://example.com/markets/banks-rally-2026-06-05/"
    FakeAsyncClient.responses = {
        section_url: httpx.Response(
            200,
            text=f'<html><body><a href="{article_url}">Banks rally</a></body></html>',
            request=httpx.Request("GET", section_url),
        ),
        article_url: httpx.Response(
            200,
            text="""<html><head>
            <meta property="og:title" content="Banks rally on policy easing">
            <meta property="og:description" content="Bank shares rose after policy easing.">
            <meta property="article:published_time" content="2026-06-05T08:00:00+00:00">
            </head><body><article>Bank shares rose after policy easing.</article></body></html>""",
            request=httpx.Request("GET", article_url),
        ),
    }
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(
        url=section_url,
        source_type="crawler",
        limit=10,
    )

    FakeAsyncClient.responses = {}
    assert result.status == "success"
    assert result.http_status == 200
    assert result.item_count == 1
    assert result.items[0].title == "Banks rally on policy easing"
    assert result.items[0].url == article_url
    assert result.items[0].description == "Bank shares rose after policy easing."


@pytest.mark.asyncio
async def test_preview_source_url_uses_crawler_user_agent_for_crawler_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section_url = "https://example.com/markets/"
    FakeAsyncClient.requests = []
    FakeAsyncClient.responses = {
        section_url: httpx.Response(
            200,
            text="<html><body></body></html>",
            request=httpx.Request("GET", section_url),
        ),
    }
    monkeypatch.setattr("common.source_preview.httpx.AsyncClient", FakeAsyncClient)

    result = await preview_source_url(url=section_url, source_type="crawler", limit=1)

    FakeAsyncClient.responses = {}
    assert result.status == "success"
    assert FakeAsyncClient.requests[0][1]["User-Agent"].startswith("market-watch-assistant/")
