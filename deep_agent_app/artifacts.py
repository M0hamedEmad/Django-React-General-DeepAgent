"""Safe metadata and ASGI streaming helpers for conversation artifacts."""

from __future__ import annotations

import asyncio
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

TEXT_PREVIEW_LIMIT = 5 * 1024 * 1024
BINARY_PREVIEW_LIMIT = 25 * 1024 * 1024
OFFICE_ENTRY_LIMIT = 2_000
OFFICE_UNCOMPRESSED_LIMIT = 100 * 1024 * 1024
STREAM_CHUNK_SIZE = 64 * 1024

TEXT_SUFFIXES = frozenset(
    {
        ".css",
        ".csv",
        ".go",
        ".h",
        ".html",
        ".htm",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".log",
        ".md",
        ".markdown",
        ".mjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
BINARY_SUFFIXES = frozenset(
    {".docx", ".jpeg", ".jpg", ".pdf", ".png", ".pptx", ".svg", ".xlsx"}
)
OFFICE_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx"})

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsx": "text/plain; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".pdf": "application/pdf",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".svg": "image/svg+xml",
    ".ts": "text/plain; charset=utf-8",
    ".tsx": "text/plain; charset=utf-8",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
}


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    name: str
    size: int
    suffix: str
    content_type: str
    preview_allowed: bool
    preview_reason: str = ""


def _office_archive_is_safe(path: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        return False, "The Office file is not a valid archive."
    if len(entries) > OFFICE_ENTRY_LIMIT:
        return False, "The Office file has too many archive entries to preview."
    if sum(entry.file_size for entry in entries) > OFFICE_UNCOMPRESSED_LIMIT:
        return False, "The expanded Office file is too large to preview."
    return True, ""


def artifact_metadata(path: Path) -> ArtifactMetadata:
    size = path.stat().st_size
    suffix = path.suffix.lower()
    content_type = CONTENT_TYPES.get(suffix)
    if content_type is None:
        content_type = (
            "text/plain; charset=utf-8"
            if suffix in TEXT_SUFFIXES
            else "application/octet-stream"
        )

    if suffix in TEXT_SUFFIXES:
        allowed = size <= TEXT_PREVIEW_LIMIT
        reason = "" if allowed else "Text files above 5 MiB are download-only."
    elif suffix in BINARY_SUFFIXES:
        allowed = size <= BINARY_PREVIEW_LIMIT
        reason = "" if allowed else "Files above 25 MiB are download-only."
    else:
        allowed = False
        reason = "No browser preview is available for this file type."

    if allowed and suffix in OFFICE_SUFFIXES:
        allowed, reason = _office_archive_is_safe(path)

    return ArtifactMetadata(
        name=path.name,
        size=size,
        suffix=suffix,
        content_type=content_type,
        preview_allowed=allowed,
        preview_reason=reason,
    )


async def stream_file(path: Path) -> AsyncIterator[bytes]:
    """Read a stable open file handle without buffering it under ASGI."""
    handle = await asyncio.to_thread(path.open, "rb")
    try:
        while chunk := await asyncio.to_thread(handle.read, STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


__all__ = [
    "ArtifactMetadata",
    "artifact_metadata",
    "stream_file",
]
