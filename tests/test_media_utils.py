from src.media_utils import data_url_for_displayable_image, infer_displayable_image_mime_type


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
