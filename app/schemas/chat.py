from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document_id: UUID
    conversation_id: UUID
    question: str = Field(min_length=1, max_length=4000)


class GeneratedAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=30000)
    source_pages: list[int] = Field(max_length=100)


class AskResponse(GeneratedAnswer):
    message_id: UUID
    conversation_id: UUID


class MessageResponse(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    source_pages: list[int] = Field(default_factory=list)
