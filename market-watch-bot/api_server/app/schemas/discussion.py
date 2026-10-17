from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


class DiscussionMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message content must not be blank")
        return normalized


class DiscussionChatRequest(BaseModel):
    # "auto" lets an LLM infer the window from the conversation (24h when none);
    # "max" searches the longest configured window (settings discussion.max_days).
    timeframe: Literal["auto", "24h", "3d", "7d", "30d", "max"] = "24h"
    messages: list[DiscussionMessage] = Field(min_length=1, max_length=20)
    # Auto only: the window the chat's previous answer searched, kept by the client so a
    # follow-up retains it after older messages fall out of the bounded history.
    # Clamped to the configured maximum window server-side.
    previous_window_start: AwareDatetime | None = None
    previous_window_end: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_conversation(self) -> DiscussionChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("the final discussion message must be from the user")
        if sum(len(message.content) for message in self.messages) > 60_000:
            raise ValueError("discussion messages exceed the 60000 character limit")
        if self.previous_window_end is not None and (
            self.previous_window_start is None
            or self.previous_window_end <= self.previous_window_start
        ):
            raise ValueError("previous_window_end must be after previous_window_start")
        return self


class DiscussionSourceRead(BaseModel):
    id: str
    title: str
    url: str
    source_name: str
    published_at: datetime | None = None


class DiscussionSettingsRead(BaseModel):
    max_window_days: int
    event_limit: int
    articles_per_event: int
    article_text_chars: int


class DiscussionContextWindowRead(BaseModel):
    # Articles published in [start, end); end null means up to now.
    start: datetime
    end: datetime | None = None
    label: str
    source: Literal["selected", "inferred", "carried", "fallback"]


class DiscussionChatResponse(BaseModel):
    status: Literal["answered", "no_context"]
    answer: str
    sources: list[DiscussionSourceRead] = Field(default_factory=list)
    context_window: DiscussionContextWindowRead | None = None
