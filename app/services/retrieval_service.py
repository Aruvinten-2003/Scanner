"""Page-preserving chunking and document-scoped lexical retrieval."""

import re

from app.utils.errors import ApiError


def chunk_pages(pages: list[dict]) -> list[dict]:
    chunks = []
    for page in pages:
        text = page["text"].strip()
        for index, start in enumerate(range(0, len(text), 1400)):
            chunk = text[start:start + 1600].strip()
            if chunk:
                chunks.append({"page_number": page["page_number"], "chunk_index": index, "chunk_text": chunk})
    if not chunks:
        raise ApiError(422, "no_text", "No readable text was found. Try a clearer scan.")
    return chunks


def select_context(chunks: list[dict], question: str, max_chars: int,
                   whole_document: bool = False) -> tuple[list[dict], bool]:
    if sum(len(c["chunk_text"]) for c in chunks) <= max_chars:
        return chunks, False
    if whole_document:
        # Evenly sample the entire document, not just its opening pages.
        count = max(1, max_chars // 1600)
        indexes = sorted({round(i * (len(chunks) - 1) / max(1, count - 1)) for i in range(count)})
        ranked = [chunks[i] for i in indexes]
    else:
        terms = set(re.findall(r"\w+", question.casefold()))
        ranked = sorted(chunks, key=lambda c: sum(
            min(c["chunk_text"].casefold().count(term), 5) for term in terms if len(term) > 1
        ), reverse=True)
    result, size = [], 0
    for chunk in ranked:
        if size + len(chunk["chunk_text"]) > max_chars:
            continue
        result.append(chunk)
        size += len(chunk["chunk_text"])
    return sorted(result, key=lambda c: (c["page_number"], c["chunk_index"])), True


class RetrievalService:
    def __init__(self, settings, database, ai):
        self.settings, self.database, self.ai = settings, database, ai

    async def ask(self, user, document_id: str, question: str, history=None, whole_document=False):
        chunks = await self.database.chunks(user, document_id)
        context, partial = select_context(chunks, question, self.settings.max_context_chars, whole_document)
        answer = await self.ai.answer(question, context, history or [], partial)
        if whole_document and partial:
            answer.answer = "Coverage note: this result uses excerpts sampled across the document. Some details may be omitted.\n\n" + answer.answer
        return answer
