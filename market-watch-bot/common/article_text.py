from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from common.source_policies import article_fetch_headers, boilerplate_text_rules, html_drop_rules

ARTICLE_FETCH_HEADERS = article_fetch_headers()


def extract_article_text(html: str, *, url: str | None = None) -> str | None:
    cleaned_html = _prune_non_article_html(html, url=url)
    try:
        import trafilatura  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional dependency fallback keeps tests lightweight
        trafilatura = None
    if trafilatura is not None:
        try:
            text = trafilatura.extract(cleaned_html, url=url)
        except TypeError:
            text = trafilatura.extract(cleaned_html)
        if text:
            return _clean_extracted_text(text, url=url)
    text = re.sub(r"<(script|style).*?</\1>", " ", cleaned_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_extracted_text(text, url=url)


def _prune_non_article_html(html: str, *, url: str | None) -> str:
    try:
        from lxml import html as lxml_html
    except Exception:  # noqa: BLE001 - fallback keeps extraction available without lxml
        return html
    try:
        document = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - malformed HTML should still use text fallback
        return html

    domain = urlsplit(url).netloc.lower() if url else ""
    for element in list(document.iter()):
        if _should_drop_element(element, domain=domain, url=url):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
    try:
        return lxml_html.tostring(document, encoding="unicode")
    except Exception:  # noqa: BLE001 - original HTML is safer than failing extraction
        return html


def _should_drop_element(element, *, domain: str, url: str | None) -> bool:
    raw_classes = str(element.get("class") or "")
    class_tokens = {token.strip().lower() for token in raw_classes.split() if token.strip()}
    data_type = str(element.get("data-type") or "").strip().lower()
    return any(
        rule.matches(domain=domain, class_tokens=class_tokens, data_type=data_type)
        for rule in html_drop_rules(url)
    )


def _clean_extracted_text(text: str | None, *, url: str | None) -> str | None:
    if not text:
        return None
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"\s*\n\s*", "\n", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized).strip()
    normalized = _remove_known_promo_blocks(normalized, url=url)
    normalized = re.sub(r"\s*\n\s*", "\n", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized).strip()
    return normalized or None


def _remove_known_promo_blocks(text: str, *, url: str | None) -> str:
    result = text
    for rule in boilerplate_text_rules(url):
        result = _remove_confirmed_suffix_block(result, rule=rule)
    return result


def _remove_confirmed_suffix_block(text: str, *, rule) -> str:
    candidates = sorted(
        start
        for marker in rule.start_markers
        if (start := text.rfind(marker)) >= 0
    )
    for start in candidates:
        if len(text[:start].strip()) < rule.min_prefix_chars:
            continue
        window = text[start : start + rule.confirmation_window_chars]
        confirmation_count = sum(
            1 for confirmation in rule.confirmation_markers if confirmation in window
        )
        if confirmation_count >= rule.min_confirmation_markers:
            return text[:start].rstrip()
    return text
