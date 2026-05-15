import pytest

from src.config import SUPPORTED_FILE_SEARCH_MODELS
from src.validation import (
    MAX_FILE_SIZE_BYTES,
    image_dimensions,
    infer_mime_type,
    normalize_mime_type,
    validate_file,
    validate_model,
)


def test_supported_model_validation_accepts_documented_models():
    for model in SUPPORTED_FILE_SEARCH_MODELS:
        assert validate_model(model) == model


def test_supported_model_validation_rejects_unknown_model():
    with pytest.raises(ValueError):
        validate_model("gemini-unknown")


def test_validate_file_accepts_pdf():
    result = validate_file("notes.pdf", 10, "application/pdf", data=b"%PDF")

    assert result.is_valid
    assert result.mime_type == "application/pdf"


def test_infer_mime_type_prefers_extension_for_docx_over_bad_browser_type():
    mime_type = infer_mime_type(
        "AD-TF-03 - ThereFore Connector System Scope and Context-110425-164353.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/octet-stream",
    )

    assert mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_normalize_mime_type_rejects_invalid_type_subtype_values():
    assert normalize_mime_type("text/plain; charset=utf-8") == "text/plain"
    assert normalize_mime_type("not a mime type") is None
    assert normalize_mime_type("application/pdf, application/octet-stream") is None


def test_validate_file_rejects_too_large_file():
    result = validate_file("notes.pdf", MAX_FILE_SIZE_BYTES + 1, "application/pdf")

    assert not result.is_valid
    assert "100 MB" in result.errors[0]


def test_validate_file_rejects_unsupported_mime_type():
    result = validate_file("song.mp3", 100, "audio/mpeg")

    assert not result.is_valid
    assert "allowlist" in result.errors[0]


def test_png_dimension_validation_rejects_over_4k():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (5000).to_bytes(4, "big") + (100).to_bytes(4, "big")

    result = validate_file("large.png", len(png), "image/png", data=png)

    assert not result.is_valid
    assert "4K x 4K" in result.errors[0]
    assert image_dimensions(png, "image/png") == (5000, 100)
