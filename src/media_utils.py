from __future__ import annotations

import base64


DISPLAYABLE_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/avif",
}
MAX_INLINE_IMAGE_BYTES = 8 * 1024 * 1024


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
