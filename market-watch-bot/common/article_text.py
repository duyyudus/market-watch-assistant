from __future__ import annotations

import re


def extract_article_text(html: str) -> str | None:
    try:
        import trafilatura  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional dependency fallback keeps tests lightweight
        trafilatura = None
    if trafilatura is not None:
        text = trafilatura.extract(html)
        if text:
            return text.strip()
    text = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
