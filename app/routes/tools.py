import asyncio

from fastapi import APIRouter, Depends, Request

from app.dependencies import current_user
from app.schemas.tools import ToolName, ToolRequest, ToolResponse
from app.services.supabase_service import UserContext
from app.utils.errors import ApiError

router = APIRouter(prefix="/tools", tags=["tools"])
PROMPTS = {
    ToolName.summary: "Summarize the document's main argument, important evidence and conclusions. Include page citations.",
    ToolName.notes: "Create organized study notes with key concepts, definitions, evidence and review prompts. Include page citations.",
    ToolName.quiz: "Create five study questions and a separate answer key, based only on the document. Cite supporting pages in the answer key.",
}


@router.post("/{tool}", response_model=ToolResponse)
async def generate_tool(tool: ToolName, body: ToolRequest, request: Request,
                        user: UserContext = Depends(current_user)):
    state = request.app.state
    document_id = str(body.document_id)
    async with state.admission.work(user.id, "tool:" + document_id):
        try:
            async with asyncio.timeout(state.settings.request_timeout_seconds):
                answer = await state.retrieval.ask(user, document_id, PROMPTS[tool], whole_document=True)
                # Verify ownership again before releasing generated document content.
                await state.database.document(user, document_id)
                return ToolResponse(document_id=document_id, tool=tool, content=answer.answer,
                                    source_pages=answer.source_pages)
        except TimeoutError:
            raise ApiError(504, "tool_timeout", "The result took too long. Please try again.") from None
