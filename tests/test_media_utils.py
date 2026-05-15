from src.media_utils import (
    data_url_for_displayable_image,
    infer_displayable_image_mime_type,
    infer_gemini_query_image_mime_type,
    validate_query_image,
)


def test_infer_displayable_image_mime_types():
    assert infer_displayable_image_mime_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert infer_displayable_image_mime_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert infer_displayable_image_mime_type(b"GIF89arest") == "image/gif"
    assert infer_displayable_image_mime_type(b"RIFF\x00\x00\x00\x00WEBPrest") == "image/webp"
    assert infer_displayable_image_mime_type(b"BMrest") == "image/bmp"
    assert infer_displayable_image_mime_type(b"\x00\x00\x00\x18ftypavifrest") == "image/avif"


def test_data_url_for_displayable_image_rejects_unknown_bytes():
    assert data_url_for_displayable_image(b"not an image") is None


def test_data_url_for_displayable_image_uses_declared_browser_safe_mime_type():
    data_url = data_url_for_displayable_image(b"GIF89arest", "image/gif")

    assert data_url is not None
    assert data_url.startswith("data:image/gif;base64,")


def test_validate_query_image_accepts_gemini_supported_formats():
    result = validate_query_image("diagram.webp", b"RIFF\x00\x00\x00\x00WEBPrest", "application/octet-stream")

    assert result.is_valid
    assert result.mime_type == "image/webp"


def test_validate_query_image_rejects_unsupported_image_format():
    result = validate_query_image("diagram.gif", b"GIF89arest", "image/gif")

    assert not result.is_valid
    assert "PNG, JPEG, WebP, HEIC, and HEIF" in result.errors[0]


def test_infer_gemini_query_image_mime_type_detects_heic_from_bytes():
    data = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"

    assert infer_gemini_query_image_mime_type("photo.bin", data, None) == "image/heic"
