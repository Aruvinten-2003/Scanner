"""HTTP route registry consumed by the Flutter Scanner client."""

from .chat import router as chat_router
from .documents import router as documents_router
from .tools import router as tools_router

ROUTERS = (documents_router, chat_router, tools_router)

__all__ = (
    "ROUTERS",
    "chat_router",
    "documents_router",
    "tools_router",
)
