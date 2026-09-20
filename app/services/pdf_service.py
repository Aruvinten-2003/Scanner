"""Parse hostile PDFs in a timed child process that receives no credentials."""

import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import sys


def extract(payload: dict) -> dict:
    import pymupdf

    data = base64.b64decode(payload["data"], validate=True)
    if len(data) > payload["max_bytes"]:
        raise ValueError("pdf_too_large")
    if not data.startswith(b"%PDF-"):
        raise ValueError("invalid_pdf")
    # Suppress parser diagnostics: they can contain bytes from the document.
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("encrypted_pdf")
        if not 1 <= document.page_count <= payload["max_pages"]:
            raise ValueError("page_limit")
        pages, total, scanned = [], 0, 0
        for page in document:
            text = page.get_text("text", sort=True).replace("\x00", "").strip()
            total += len(text)
            if total > payload["max_chars"]:
                raise ValueError("text_limit")
            result = {"page_number": page.number + 1, "text": text}
            if len(text) < 40 and page.get_images():
                scanned += 1
                if scanned > payload["max_ocr_pages"]:
                    raise ValueError("ocr_page_limit")
                longest = max(page.rect.width, page.rect.height)
                if longest <= 0:
                    raise ValueError("invalid_pdf")
                scale = min(2.0, 1600 / longest)
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, colorspace=pymupdf.csRGB)
                result["image"] = base64.b64encode(pixmap.tobytes("jpeg", jpg_quality=85)).decode("ascii")
            pages.append(result)
        return {"pages": pages, "page_count": document.page_count}


async def inspect_pdf(data: bytes, settings) -> dict:
    from app.utils.errors import ApiError

    if not data.startswith(b"%PDF-"):
        raise ApiError(422, "invalid_pdf", "Select a valid PDF file.")
    if len(data) > settings.max_pdf_bytes:
        raise ApiError(413, "pdf_too_large", "The PDF exceeds the upload size limit.")
    payload = json.dumps({
        "data": base64.b64encode(data).decode("ascii"), "max_bytes": settings.max_pdf_bytes,
        "max_pages": settings.max_pdf_pages, "max_chars": settings.max_text_chars,
        "max_ocr_pages": settings.max_ocr_pages,
    }).encode()
    environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(Path(__file__).resolve()), "--worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(payload), settings.pdf_timeout_seconds)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise ApiError(422, "pdf_timeout", "The PDF took too long to read. Try a smaller document.") from None
    try:
        parsed = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(422, "invalid_pdf", "Scanner could not read this PDF.") from None
    messages = {
        "encrypted_pdf": "Remove the PDF password before uploading it.",
        "page_limit": "This PDF exceeds the configured page limit.",
        "text_limit": "This PDF contains too much text. Split it into smaller documents.",
        "ocr_page_limit": "This PDF has too many scanned pages. Split it into smaller documents.",
        "pdf_too_large": "The PDF exceeds the upload size limit.",
    }
    if process.returncode or "error" in parsed:
        code = parsed.get("error", "invalid_pdf")
        raise ApiError(422, code, messages.get(code, "Scanner could not read this PDF."))
    return parsed


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(40_000_000))
        result = extract(request)
    except ValueError as error:
        known = {"invalid_pdf", "encrypted_pdf", "page_limit", "text_limit", "ocr_page_limit", "pdf_too_large"}
        result = {"error": str(error) if str(error) in known else "invalid_pdf"}
    except Exception:
        result = {"error": "invalid_pdf"}
    sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))
