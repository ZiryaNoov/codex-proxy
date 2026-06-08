"""Document conversion service using MarkItDown.

Wraps Microsoft's MarkItDown library for converting files (PDF, DOCX, XLSX,
PPTX, HTML, images, audio, etc.) to Markdown. MarkItDown is synchronous,
so conversions are offloaded to a thread executor.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from pathlib import Path

logger = logging.getLogger("codex-proxy.documents")

# Supported file extensions (mapped to what MarkItDown handles)
SUPPORTED_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".xml",
    ".json", ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
    ".wav", ".mp3", ".m4a",
    ".ipynb",
    ".zip",  # MarkItDown can extract and convert contents
})

MAX_FILE_SIZE_DEFAULT = 50 * 1024 * 1024  # 50 MB

# Lazy singleton — MarkItDown instance
_markitdown_instance = None


def _get_markitdown():  # type: ignore[no-untyped-def]
    """Lazy singleton for MarkItDown converter."""
    global _markitdown_instance
    if _markitdown_instance is None:
        try:
            from markitdown import MarkItDown
            _markitdown_instance = MarkItDown()
            logger.info("MarkItDown converter initialized")
        except ImportError as exc:
            raise RuntimeError(
                "markitdown is not installed. Install with: pip install codex-proxy[documents]"
            ) from exc
    return _markitdown_instance


def validate_file(
    filename: str,
    file_size: int,
    max_size: int = MAX_FILE_SIZE_DEFAULT,
    allowed_extensions: set[str] | None = None,
) -> str | None:
    """Validate an uploaded file.

    Returns None on success, or an error message string on failure.
    """
    if not filename:
        return "Filename is required"

    # Check extension
    ext = Path(filename).suffix.lower()
    if not ext:
        return "File has no extension"

    effective_allowed = allowed_extensions or SUPPORTED_EXTENSIONS
    if ext not in effective_allowed:
        return f"Unsupported file type: {ext}. Supported: {', '.join(sorted(effective_allowed))}"

    # Check size
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        return f"File too large: {file_size} bytes. Maximum: {max_mb:.0f} MB"

    if file_size == 0:
        return "File is empty"

    return None


async def convert_file(file_path: str | Path) -> tuple[str, str | None]:
    """Convert a file to Markdown using MarkItDown.

    Runs in a thread executor since MarkItDown is synchronous.
    Returns (markdown_text, title) tuple.
    """
    md = _get_markitdown()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, md.convert_local, str(file_path))
    return result.text_content, getattr(result, "title", None)


async def save_upload_file(upload_file, dest_dir: Path) -> Path:
    """Save a FastAPI UploadFile to dest_dir with a unique name.

    Returns the path to the saved file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename to avoid collisions
    original_name = upload_file.filename or "unknown"
    unique_name = f"{uuid.uuid4().hex[:12]}-{original_name}"
    dest_path = dest_dir / unique_name

    content = await upload_file.read()
    dest_path.write_bytes(content)
    await upload_file.seek(0)  # Reset for potential re-read

    return dest_path


async def convert_and_cleanup(file_path: str | Path) -> tuple[str, str | None]:
    """Convert a file to Markdown, then delete the temp file.

    Returns (markdown_text, title) tuple.
    """
    path = Path(file_path)
    try:
        markdown, title = await convert_file(path)
        return markdown, title
    finally:
        # Always clean up temp file
        with suppress(OSError):
            path.unlink(missing_ok=True)


def get_file_type(filename: str) -> str:
    """Extract the file type/extension without the dot."""
    return Path(filename).suffix.lower().lstrip(".")
