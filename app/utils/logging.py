"""Logs contain route templates and status codes, never tokens or content."""

import json
import logging


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "level": record.levelname,
            "event": getattr(record, "event", "server_event"),
            "route": getattr(record, "route", "unmatched"),
            "status": getattr(record, "status", None),
            "request_id": getattr(record, "request_id", None),
        })


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter())
    logger = logging.getLogger("scanner")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    # Access/error logs may include URL query strings or provider exception bodies.
    for name in ("httpx", "httpcore", "httpx2", "openai", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).disabled = True
