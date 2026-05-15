from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path


DISPLAYABLE_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/avif",
}
MAX_INLINE_IMAGE_BYTES = 8 * 1024 * 1024
MAX_GEMINI_INLINE_IMAGE_BYTES = 18 * 1024 * 1024

GEMINI_QUERY_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
}

QUERY_IMAGE_EXTENSION_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


@dataclass(frozen=True)
class QueryImageValidationResult:
    is_valid: bool
    filename: str
    mime_type: str | None
    size_bytes: int
    errors: list[str]


def infer_displayable_image_mime_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and b"avif" in data[8:32]:
        return "image/avif"
    return None


def data_url_for_displayable_image(data: bytes, mime_type: str | None = None) -> str | None:
    if len(data) > MAX_INLINE_IMAGE_BYTES:
        return None
    resolved_mime_type = mime_type if mime_type in DISPLAYABLE_IMAGE_MIME_TYPES else None
    resolved_mime_type = resolved_mime_type or infer_displayable_image_mime_type(data)
    if not resolved_mime_type:
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{resolved_mime_type};base64,{encoded}"


def validate_query_image(
    filename: str,
    data: bytes,
    content_type: str | None = None,
) -> QueryImageValidationResult:
    clean_name = Path(filename).name or "query-image"
    mime_type = infer_gemini_query_image_mime_type(clean_name, data, content_type)
    errors: list[str] = []
    if not data:
        errors.append("Image is empty.")
    if len(data) > MAX_GEMINI_INLINE_IMAGE_BYTES:
        errors.append("Inline query images must be under 18 MB.")
    if not mime_type:
        errors.append("Unsupported query image type. Gemini image input supports PNG, JPEG, WebP, HEIC, and HEIF.")

    return QueryImageValidationResult(
        is_valid=not errors,
        filename=clean_name,
        mime_type=mime_type,
        size_bytes=len(data),
        errors=errors,
    )


def infer_gemini_query_image_mime_type(
    filename: str,
    data: bytes,
    content_type: str | None = None,
) -> str | None:
    normalized = _normalize_image_mime_type(content_type)
    if normalized in GEMINI_QUERY_IMAGE_MIME_TYPES:
        return normalized

    magic = infer_gemini_image_mime_type_from_bytes(data)
    if magic in GEMINI_QUERY_IMAGE_MIME_TYPES:
        return magic

    suffix = Path(filename).suffix.lower()
    return QUERY_IMAGE_EXTENSION_MIME_TYPES.get(suffix)


def infer_gemini_image_mime_type_from_bytes(data: bytes) -> str | None:
    displayable = infer_displayable_image_mime_type(data)
    if displayable in {"image/png", "image/jpeg", "image/webp"}:
        return displayable
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brands = data[8:32]
        if any(brand in brands for brand in (b"heic", b"heix", b"hevc", b"hevx")):
            return "image/heic"
        if any(brand in brands for brand in (b"mif1", b"msf1", b"heif")):
            return "image/heif"
    return None


def _normalize_image_mime_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";")[0].strip().lower()
