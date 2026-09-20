"""Supabase REST adapter with per-request identity and explicit owner filters."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx

from app.config import Settings
from app.utils.errors import ApiError


@dataclass(frozen=True, repr=False)
class UserContext:
    id: str
    token: str


class SupabaseService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    def require_config(self) -> None:
        if not self.settings.supabase_ready:
            raise ApiError(503, "storage_unconfigured", "The server database is not configured.")

    def headers(self, user: UserContext | None = None) -> dict[str, str]:
        self.require_config()
        key = self.settings.public_key if user else self.settings.server_key
        headers = {"apikey": key, "Content-Type": "application/json"}
        if user:
            headers["Authorization"] = "Bearer " + user.token
        elif key.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + key
        return headers

    async def authenticate(self, token: str) -> UserContext:
        self.require_config()
        try:
            response = await self.client.get(
                self.settings.supabase_url + "/auth/v1/user",
                headers={"apikey": self.settings.public_key, "Authorization": "Bearer " + token},
            )
            if response.status_code in (401, 403):
                raise ApiError(401, "invalid_session", "Your session has expired. Please sign in.")
            response.raise_for_status()
            data = response.json()
            # The trusted Auth server verifies signature, expiry and current user state.
            if data.get("aud") != self.settings.supabase_jwt_audience or data.get("is_anonymous") or data.get("deleted_at"):
                raise ApiError(401, "invalid_session", "Please sign in with a registered account.")
            if data.get("banned_until"):
                banned = datetime.fromisoformat(data["banned_until"].replace("Z", "+00:00"))
                if banned > datetime.now(timezone.utc):
                    raise ApiError(401, "invalid_session", "This account cannot access Scanner.")
            return UserContext(str(UUID(data["id"])), token)
        except ApiError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ApiError(503, "auth_unavailable", "Sign-in verification is temporarily unavailable.") from None

    async def rest(self, method: str, table: str, *, user: UserContext | None,
                   params: dict | None = None, body=None, prefer: str = "return=representation"):
        headers = self.headers(user)
        headers["Prefer"] = prefer
        try:
            response = await self.client.request(
                method, self.settings.supabase_url + "/rest/v1/" + table,
                headers=headers, params=params, json=body,
            )
            if response.status_code == 409:
                raise ApiError(409, "conflict", "This operation conflicts with an existing record. Retry.")
            if response.status_code in (401, 403):
                raise ApiError(403, "access_denied", "The requested operation is not permitted.")
            response.raise_for_status()
            return response.json() if response.content else []
        except (httpx.HTTPError, ValueError):
            raise ApiError(502, "database_error", "Scanner could not access the database.") from None

    @staticmethod
    def owner_filter(user: UserContext, **filters: str) -> dict[str, str]:
        return {"user_id": "eq." + user.id, **{k: "eq." + v for k, v in filters.items()}}

    async def document(self, user: UserContext, document_id: str) -> dict:
        rows = await self.rest("GET", "documents", user=user, params={
            **self.owner_filter(user, id=document_id), "select": "*", "limit": "1",
        })
        if not rows or rows[0].get("user_id") != user.id:
            raise ApiError(404, "document_not_found", "Document not found.")
        return rows[0]

    async def update_document(self, user: UserContext, document_id: str, changes: dict) -> None:
        rows = await self.rest("PATCH", "documents", user=user,
                               params=self.owner_filter(user, id=document_id), body=changes)
        if not rows:
            raise ApiError(404, "document_not_found", "Document not found.")

    @staticmethod
    def storage_path(user: UserContext, document: dict) -> str:
        # Metadata is editable by its owner: never trust it with a server credential.
        path = document.get("storage_path", "")
        parts = path.split("/")
        if (len(parts) != 3 or parts[0] != user.id or parts[1] != str(document["id"])
                or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,254}", parts[2])
                or ".." in parts[2]):
            raise ApiError(422, "invalid_storage_path", "The document has an invalid storage location.")
        return quote(path, safe="/")

    async def download(self, user: UserContext, document: dict) -> bytes:
        path = self.storage_path(user, document)
        try:
            # End-user bearer token preserves Storage RLS; redirects are disabled.
            async with self.client.stream(
                "GET", self.settings.supabase_url + "/storage/v1/object/authenticated/pdfs/" + path,
                headers=self.headers(user),
            ) as response:
                if response.status_code == 404:
                    raise ApiError(404, "file_not_found", "The PDF is no longer in storage.")
                response.raise_for_status()
                size = int(response.headers.get("content-length", "0"))
                if size > self.settings.max_pdf_bytes:
                    raise ApiError(413, "pdf_too_large", "The PDF exceeds the upload size limit.")
                data = bytearray()
                async for part in response.aiter_bytes():
                    data.extend(part)
                    if len(data) > self.settings.max_pdf_bytes:
                        raise ApiError(413, "pdf_too_large", "The PDF exceeds the upload size limit.")
                return bytes(data)
        except (httpx.HTTPError, ValueError):
            raise ApiError(502, "download_failed", "Scanner could not download the PDF.") from None

    async def replace_chunks(self, user: UserContext, document_id: str, chunks: list[dict]) -> None:
        await self.document(user, document_id)
        params = self.owner_filter(user, document_id=document_id)
        await self.rest("DELETE", "document_chunks", user=None, params=params)
        try:
            for offset in range(0, len(chunks), 100):
                rows = [{**chunk, "user_id": user.id, "document_id": document_id}
                        for chunk in chunks[offset:offset + 100]]
                await self.rest("POST", "document_chunks", user=None, body=rows, prefer="return=minimal")
        except Exception:
            await self.rest("DELETE", "document_chunks", user=None, params=params)
            raise

    async def chunks(self, user: UserContext, document_id: str) -> list[dict]:
        document = await self.document(user, document_id)
        if document["status"] != "ready":
            raise ApiError(409, "document_not_ready", "Finish processing the PDF first.")
        result = []
        # Two equality filters are mandatory for privileged, server-only chunk reads.
        for offset in range(0, 2500, 500):
            rows = await self.rest("GET", "document_chunks", user=None, params={
                **self.owner_filter(user, document_id=document_id),
                "select": "page_number,chunk_index,chunk_text", "order": "page_number,chunk_index",
                "offset": str(offset), "limit": "500",
            })
            result.extend(rows)
            if len(rows) < 500:
                break
        if not result:
            raise ApiError(409, "document_not_indexed", "Process the PDF before asking questions.")
        return result

    async def conversation(self, user: UserContext, conversation_id: str,
                           document_id: str | None = None, title: str = "New conversation") -> dict:
        if document_id:
            await self.document(user, document_id)
        rows = await self.rest("GET", "conversations", user=user, params={
            **self.owner_filter(user, id=conversation_id), "select": "*", "limit": "1",
        })
        if not rows:
            if not document_id:
                raise ApiError(404, "conversation_not_found", "Conversation not found.")
            rows = await self.rest("POST", "conversations", user=user, body={
                "id": conversation_id, "user_id": user.id, "document_id": document_id, "title": title[:160],
            })
        row = rows[0]
        if row["user_id"] != user.id or (document_id and row["document_id"] != document_id):
            raise ApiError(404, "conversation_not_found", "Conversation not found for this document.")
        await self.document(user, row["document_id"])
        return row

    async def messages(self, user: UserContext, conversation_id: str, limit: int = 100) -> list[dict]:
        await self.conversation(user, conversation_id)
        rows = await self.rest("GET", "messages", user=user, params={
            **self.owner_filter(user, conversation_id=conversation_id),
            "select": "id,role,content,created_at,source_pages", "order": "created_at.desc,id.desc",
            "limit": str(limit),
        })
        return list(reversed(rows))

    async def save_exchange(self, user: UserContext, conversation_id: str,
                            document_id: str, question: str, answer: str, pages: list[int]) -> str:
        # Recheck after AI finishes in case the conversation was deleted or reassigned.
        await self.conversation(user, conversation_id, document_id)
        answer_id = str(uuid4())
        common = {"user_id": user.id, "conversation_id": conversation_id}
        await self.rest("POST", "messages", user=user, body=[
            {**common, "id": str(uuid4()), "role": "user", "content": question, "source_pages": [],
             "created_at": datetime.now(timezone.utc).isoformat()},
            {**common, "id": answer_id, "role": "assistant", "content": answer, "source_pages": pages,
             "created_at": datetime.now(timezone.utc).isoformat()},
        ])
        return answer_id
