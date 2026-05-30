from __future__ import annotations

from pydantic import BaseModel


class ListEnvelope[T](BaseModel):
    items: list[T]
    total: int
