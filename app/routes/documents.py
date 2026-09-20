import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.dependencies import current_user
from app.schemas.document import ProcessDocumentResponse
from app.services.pdf_service import inspect_pdf
from app.services.retrieval_service import chunk_pages
from app.services.supabase_service import UserContext
from app.utils.errors import ApiError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/{document_id}/process", response_model=ProcessDocumentResponse)
async def process_document(document_id: UUID, request: Request, user: UserContext = Depends(current_user)):
    state = request.app.state
    document_id = str(document_id)
    document = await state.database.document(user, document_id)
    async with state.admission.work(user.id, "document:" + document_id):
        await state.database.update_document(user, document_id, {"status": "processing", "error_message": None})
        try:
            async with asyncio.timeout(state.settings.request_timeout_seconds):
                data = await state.database.download(user, document)
                parsed = await inspect_pdf(data, state.settings)
                ocr_pages = [page for page in parsed["pages"] if page.get("image")]
                semaphore = asyncio.Semaphore(2)

                async def transcribe(page):
                    async with semaphore:
                        page["text"] = await state.ai.transcribe(page.pop("image"))

                async with asyncio.TaskGroup() as group:
                    for page in ocr_pages:
                        group.create_task(transcribe(page))
                if sum(len(page["text"]) for page in parsed["pages"]) > state.settings.max_text_chars:
                    raise ApiError(422, "text_limit", "Split this PDF into smaller documents.")
                chunks = chunk_pages(parsed["pages"])
                await state.database.replace_chunks(user, document_id, chunks)
                await state.database.update_document(user, document_id, {
                    "status": "ready", "page_count": parsed["page_count"],
                    "retrieval_id": None, "error_message": None,
                })
                return ProcessDocumentResponse(document_id=document_id, page_count=parsed["page_count"],
                                               chunk_count=len(chunks), ocr_pages=len(ocr_pages))
        except (Exception, asyncio.CancelledError) as error:
            public_error = error
            if isinstance(error, ExceptionGroup):
                public_error = next((exc for exc in error.exceptions if isinstance(exc, ApiError)), error)
            if isinstance(public_error, TimeoutError):
                public_error = ApiError(504, "processing_timeout", "Processing took too long. Try a smaller PDF.")
            if not isinstance(public_error, ApiError):
                public_error = ApiError(500, "processing_failed", "Scanner could not process this PDF. Please retry.")
            try:
                await state.database.update_document(user, document_id, {
                    "status": "failed", "error_message": public_error.message,
                })
            except Exception:
                pass  # A deleted document or unavailable database must not disclose an internal error.
            if isinstance(error, asyncio.CancelledError):
                raise
            raise public_error from None
