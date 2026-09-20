"""Authentication and bounded per-user admission for expensive work."""

from collections import OrderedDict
from contextlib import asynccontextmanager
import time

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.supabase_service import UserContext
from app.utils.errors import ApiError

bearer = HTTPBearer(auto_error=False)


class AdmissionControl:
    """Single-process limits; use an API gateway for limits across replicas."""
    def __init__(self, limit: int, concurrency: int):
        self.limit, self.concurrency = limit, concurrency
        self.windows: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self.active: set[tuple[str, str]] = set()

    def check(self, user_id: str) -> None:
        now = time.monotonic()
        while self.windows and next(iter(self.windows.values()))[0] + 60 <= now:
            self.windows.popitem(last=False)
        start, count = self.windows.get(user_id, (now, 0))
        if count >= self.limit:
            raise ApiError(429, "rate_limited", "Too many requests. Please wait a minute.")
        if user_id not in self.windows and len(self.windows) >= 10000:
            raise ApiError(503, "server_busy", "The server is busy. Please try again shortly.")
        self.windows[user_id] = (start, count + 1)

    @asynccontextmanager
    async def work(self, user_id: str, resource: str):
        key = (user_id, resource)
        if key in self.active:
            raise ApiError(409, "already_processing", "This document or conversation is already being processed.")
        if len(self.active) >= self.concurrency:
            raise ApiError(429, "server_busy", "The server is busy. Please try again shortly.")
        self.active.add(key)
        try:
            yield
        finally:
            self.active.discard(key)


async def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UserContext:
    if credentials is None or credentials.scheme.lower() != "bearer" or not 20 <= len(credentials.credentials) <= 8192:
        raise ApiError(401, "authentication_required", "Sign in to access your documents.")
    user = await request.app.state.database.authenticate(credentials.credentials)
    request.app.state.admission.check(user.id)
    return user
