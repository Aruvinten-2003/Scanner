from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ProcessDocumentResponse(BaseModel):
    document_id: UUID
    status: Literal["ready"] = "ready"
    page_count: int
    chunk_count: int
    ocr_pages: int = 0
