from __future__ import annotations

import mimetypes
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .config import SUPPORTED_FILE_SEARCH_MODELS


MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_DIMENSION_PX = 4096

EXTENSION_MIME_OVERRIDES: dict[str, str] = {
    ".csv": "text/csv",
    ".css": "text/css",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
    ".java": "text/x-java-source",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".php": "application/x-php",
    ".png": "image/png",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ps1": "application/x-powershell",
    ".py": "text/x-python",
    ".rb": "text/x-ruby-script",
    ".rst": "text/x-rst",
    ".rtf": "text/rtf",
    ".sh": "application/x-sh",
    ".sql": "application/sql",
    ".tex": "application/x-tex",
    ".ts": "application/typescript",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".zip": "application/zip",
}

SUPPORTED_MIME_TYPES: set[str] = {
    "application/dart",
    "application/ecmascript",
    "application/json",
    "application/ms-java",
    "application/msword",
    "application/pdf",
    "application/sql",
    "application/typescript",
    "application/vnd.ms-excel",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "application/x-csh",
    "application/x-latex",
    "application/x-php",
    "application/x-powershell",
    "application/x-sh",
    "application/x-shellscript",
    "application/x-tex",
    "application/xml",
    "application/zip",
    "image/jpeg",
    "image/png",
    "text/css",
    "text/csv",
    "text/html",
    "text/javascript",
    "text/markdown",
    "text/plain",
    "text/rtf",
    "text/tab-separated-values",
    "text/tsx",
    "text/x-c",
    "text/x-c++hdr",
    "text/x-c++src",
    "text/x-csharp",
    "text/x-go",
    "text/x-java",
    "text/x-java-source",
    "text/x-python",
    "text/x-python-script",
    "text/x-r-markdown",
    "text/x-rst",
    "text/x-ruby-script",
    "text/x-rust",
    "text/x-scss",
    "text/x-sql",
    "text/x-swift",
    "text/x-tex",
    "text/xml",
    "text/yaml",
}

MIME_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


@dataclass(frozen=True)
class FileValidationResult:
    is_valid: bool
    filename: str
    mime_type: str | None
    size_bytes: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    image_dimensions: tuple[int, int] | None = None


def is_supported_model(model: str) -> bool:
    return model in SUPPORTED_FILE_SEARCH_MODELS


def validate_model(model: str) -> str:
    if not model or not model.startswith("gemini-"):
        raise ValueError(f"Unsupported File Search model: {model}")
    return model


def accepted_extensions() -> list[str]:
    return sorted(ext.lstrip(".") for ext in EXTENSION_MIME_OVERRIDES)


def infer_mime_type(filename: str, content_type: str | None = None) -> str | None:
    suffix = Path(filename).suffix.lower()
    if suffix in EXTENSION_MIME_OVERRIDES:
        return EXTENSION_MIME_OVERRIDES[suffix]

    normalized_content_type = normalize_mime_type(content_type)
    if normalized_content_type and normalized_content_type != "application/octet-stream":
        return normalized_content_type

    guessed, _ = mimetypes.guess_type(filename)
    return normalize_mime_type(guessed)


def normalize_mime_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    candidate = content_type.split(";")[0].strip().lower()
    if not MIME_TYPE_PATTERN.match(candidate):
        return None
    return candidate


def validate_file(
    filename: str,
    size_bytes: int,
    content_type: str | None = None,
    data: bytes | None = None,
) -> FileValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    clean_name = Path(filename).name
    if not clean_name:
        errors.append("Filename is required.")

    if size_bytes <= 0:
        errors.append("File is empty.")
    if size_bytes > MAX_FILE_SIZE_BYTES:
        errors.append("File exceeds the 100 MB File Search per-document limit.")

    mime_type = infer_mime_type(clean_name, content_type)
    if not mime_type:
        errors.append("Could not infer a supported MIME type.")
    elif mime_type not in SUPPORTED_MIME_TYPES:
        errors.append(f"MIME type is not in this app's supported File Search allowlist: {mime_type}")

    dimensions = None
    if mime_type in {"image/png", "image/jpeg"} and data is not None:
        dimensions = image_dimensions(data, mime_type)
        if dimensions is None:
            warnings.append("Image dimensions could not be verified locally; Google will enforce image limits.")
        else:
            width, height = dimensions
            if width > MAX_IMAGE_DIMENSION_PX or height > MAX_IMAGE_DIMENSION_PX:
                errors.append("Images must be at most 4K x 4K pixels for multimodal File Search.")

    return FileValidationResult(
        is_valid=not errors,
        filename=clean_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        errors=errors,
        warnings=warnings,
        image_dimensions=dimensions,
    )


def image_dimensions(data: bytes, mime_type: str) -> tuple[int, int] | None:
    if mime_type == "image/png":
        return _png_dimensions(data)
    if mime_type == "image/jpeg":
        return _jpeg_dimensions(data)
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    try:
        return struct.unpack(">II", data[16:24])
    except struct.error:
        return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        return None

    offset = 2
    while offset < len(data):
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None

        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None

        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            return None

        if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
            if segment_length < 7:
                return None
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height

        offset += segment_length
    return None


def safe_display_name(filename: str) -> str:
    name = Path(filename).name.strip()
    name = re.sub(r"\s+", " ", name)
    return name[:512] if name else "uploaded-file"
