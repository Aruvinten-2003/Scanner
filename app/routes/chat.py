import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.dependencies import current_user
from app.schemas.chat import AskRequest, AskResponse, MessageResponse
from app.services.supabase_service import UserContext
from app.utils.errors import ApiError

router = APIRouter(tags=["chat"])


@router.post("/chat/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request, user: UserContext = Depends(current_user)):
    state = request.app.state
    document_id, conversation_id = str(body.document_id), str(body.conversation_id)
    async with state.admission.work(user.id, "conversation:" + conversation_id):
        try:
            async with asyncio.timeout(state.settings.request_timeout_seconds):
                await state.database.conversation(user, conversation_id, document_id, body.question)
                history = await state.database.messages(user, conversation_id, limit=6)
                answer = await state.retrieval.ask(user, document_id, body.question, history)
                message_id = await state.database.save_exchange(
                    user, conversation_id, document_id, body.question, answer.answer, answer.source_pages,
                )
                return AskResponse(message_id=message_id, conversation_id=conversation_id,
                                   answer=answer.answer, source_pages=answer.source_pages)
        except TimeoutError:
            raise ApiError(504, "answer_timeout", "The answer took too long. Please try again.") from None


@router.get("/messages/{conversation_id}", response_model=list[MessageResponse])
async def messages(conversation_id: UUID, request: Request, limit: int = Query(default=100, ge=1, le=200),
                   user: UserContext = Depends(current_user)):
    return await request.app.state.database.messages(user, str(conversation_id), limit)
