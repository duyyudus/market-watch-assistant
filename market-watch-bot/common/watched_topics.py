"""Shared persisted topic preferences for digest generation."""
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AppSetting

TopicPhrase = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class WatchedTopics(BaseModel):
    topics: list[TopicPhrase] = Field(default_factory=list, max_length=30)

    @field_validator("topics")
    @classmethod
    def unique_topics(cls, topics: list[str]) -> list[str]:
        if len({topic.casefold() for topic in topics}) != len(topics):
            raise ValueError("Topic phrases must be unique")
        return topics


async def get_watched_topics(session: AsyncSession) -> WatchedTopics:
    setting = await session.get(AppSetting, "watched_topics")
    return WatchedTopics.model_validate(setting.value) if setting else WatchedTopics()


async def save_watched_topics(session: AsyncSession, payload: WatchedTopics) -> WatchedTopics:
    setting = await session.get(AppSetting, "watched_topics")
    if setting is None:
        session.add(AppSetting(key="watched_topics", value=payload.model_dump()))
    else:
        setting.value = payload.model_dump()
    await session.flush()
    return payload
