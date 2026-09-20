from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ToolName(StrEnum):
    summary = "summary"
    notes = "notes"
    quiz = "quiz"


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID


class ToolResponse(BaseModel):
    document_id: UUID
    tool: ToolName
    content: str
    source_pages: list[int]
