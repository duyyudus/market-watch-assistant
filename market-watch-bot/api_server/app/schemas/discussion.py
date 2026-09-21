from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    timeframe: Literal["24h", "3d", "7d", "30d"] = "24h"
    messages: list[DiscussionMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_conversation(self) -> DiscussionChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("the final discussion message must be from the user")
        if sum(len(message.content) for message in self.messages) > 60_000:
            raise ValueError("discussion messages exceed the 60000 character limit")
        return self


class DiscussionSourceRead(BaseModel):
    id: str
    title: str
    url: str
    source_name: str
    published_at: datetime | None = None


class DiscussionChatResponse(BaseModel):
    status: Literal["answered", "no_context"]
    answer: str
    sources: list[DiscussionSourceRead] = Field(default_factory=list)
