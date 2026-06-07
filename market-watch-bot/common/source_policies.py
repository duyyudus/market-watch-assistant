from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_ARTICLE_FETCH_HEADERS = {
    "User-Agent": "market-watch-assistant/0.1 (+https://github.com/market-watch-assistant)"
}


@dataclass(frozen=True)
class SourceFetchRequest:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class HtmlDropRule:
    class_tokens: frozenset[str] = frozenset()
    data_types: frozenset[str] = frozenset()
    domain_suffixes: tuple[str, ...] = ()
    required_class_tokens: frozenset[str] = frozenset()

    def matches(self, *, domain: str, class_tokens: set[str], data_type: str) -> bool:
        if self.domain_suffixes and not any(
            domain.endswith(suffix) for suffix in self.domain_suffixes
        ):
            return False
        if self.class_tokens and class_tokens & self.class_tokens:
            return True
        if self.data_types and data_type in self.data_types:
            return True
        return bool(self.required_class_tokens and self.required_class_tokens <= class_tokens)


@dataclass(frozen=True)
class BoilerplateTextRule:
    start_markers: tuple[str, ...]
    confirmation_markers: tuple[str, ...]
    min_prefix_chars: int = 80
    confirmation_window_chars: int = 1_200
    min_confirmation_markers: int = 3


GLOBAL_HTML_DROP_RULES = (
    HtmlDropRule(
        class_tokens=frozenset(
            {"advertisement", "ads", "ad-container", "related-news", "box-vif"}
        ),
        data_types=frozenset({"boxcontent"}),
    ),
)

VIETNAMBIZ_PROMO_START_MARKERS = (
    "Diễn đàn Đầu tư Việt Nam",
    "Vietnam Investment Forum",
    "Thời gian:",
    "Địa điểm:",
)

VIETNAMBIZ_PROMO_CONFIRMATION_MARKERS = (
    "Thời gian:",
    "Địa điểm:",
    "phiên thảo luận",
    "thảo luận chính",
    "Tham gia khảo sát",
    "Đặt vé",
    "Early Bird",
    "Investment Forum",
    "Diễn đàn Đầu tư",
    "VIF",
    "Summit",
    "Forum",
    "tham gia",
    "khảo sát",
)

DOMAIN_HTML_DROP_RULES = {
    "vietnambiz.vn": (
        HtmlDropRule(
            data_types=frozenset({"boxcontent", "simpleimage"}),
            required_class_tokens=frozenset({"vnbizpreviewmode", "align-center"}),
        ),
    ),
    "vneconomy.vn": (
        HtmlDropRule(
            class_tokens=frozenset(
                {
                    "list-detail-revert_item",
                    "box-keyword",
                    "block-job-same",
                    "main-job-ndt",
                    "news-general",
                    "news-general_multimedia",
                    "news-general_wapper",
                    "zone--event",
                    "chatbot-askonomy-ai",
                }
            ),
        ),
    ),
}

DOMAIN_TEXT_RULES = {
    "vietnambiz.vn": (
        BoilerplateTextRule(
            start_markers=VIETNAMBIZ_PROMO_START_MARKERS,
            confirmation_markers=VIETNAMBIZ_PROMO_CONFIRMATION_MARKERS,
        ),
    )
}
GLOBAL_TEXT_RULES: tuple[BoilerplateTextRule, ...] = ()


def article_fetch_headers() -> dict[str, str]:
    return dict(DEFAULT_ARTICLE_FETCH_HEADERS)


def crawler_fetch_headers() -> dict[str, str]:
    return article_fetch_headers()


def source_fetch_request(url: str, headers: dict[str, str] | None = None) -> SourceFetchRequest:
    request_headers = dict(headers or {})
    return SourceFetchRequest(url=url, headers=request_headers)


def html_drop_rules(url: str | None) -> tuple[HtmlDropRule, ...]:
    domain = _domain(url)
    return GLOBAL_HTML_DROP_RULES + _domain_rules(DOMAIN_HTML_DROP_RULES, domain)


def boilerplate_text_rules(url: str | None) -> tuple[BoilerplateTextRule, ...]:
    return GLOBAL_TEXT_RULES + _domain_rules(DOMAIN_TEXT_RULES, _domain(url))


def _domain(url: str | None) -> str:
    return urlsplit(url).netloc.lower() if url else ""


def _domain_rules(rules: dict[str, tuple], domain: str) -> tuple:
    matched: list = []
    for suffix, suffix_rules in rules.items():
        if domain.endswith(suffix):
            matched.extend(suffix_rules)
    return tuple(matched)
