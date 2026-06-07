from __future__ import annotations


def first_article_fallback_text(*values: str | None) -> str:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return ""
