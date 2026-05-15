from __future__ import annotations

from dataclasses import dataclass


class PDFPreviewError(Exception):
    """Raised when a PDF page cannot be rendered for local preview."""


@dataclass(frozen=True)
class PDFPagePreview:
    page_number: int
    page_count: int
    png_bytes: bytes


def render_pdf_page_png(
    data: bytes,
    page_number: int | None = None,
    zoom: float = 1.6,
) -> PDFPagePreview:
    try:
        import fitz
    except ImportError as exc:
        raise PDFPreviewError(
            "PDF page previews require PyMuPDF. Install requirements.txt and restart the app."
        ) from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PDFPreviewError(f"Could not open PDF for preview: {exc}") from exc

    try:
        if document.page_count < 1:
            raise PDFPreviewError("PDF has no pages to preview.")
        requested_page = page_number or 1
        page_index = min(max(requested_page, 1), document.page_count) - 1
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return PDFPagePreview(
            page_number=page_index + 1,
            page_count=document.page_count,
            png_bytes=pixmap.tobytes("png"),
        )
    except PDFPreviewError:
        raise
    except Exception as exc:
        raise PDFPreviewError(f"Could not render PDF page preview: {exc}") from exc
    finally:
        document.close()
