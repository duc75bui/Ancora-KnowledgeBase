from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path

from .validation import safe_display_name


class PDFSplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class PDFPart:
    file_path: Path
    filename: str
    page_start: int
    page_end: int
    page_count: int
    part_index: int
    part_count: int


@dataclass(frozen=True)
class PDFSplitResult:
    original_page_count: int
    parts: list[PDFPart]


def split_pdf_bytes(
    data: bytes,
    original_filename: str,
    output_root: Path,
    pages_per_part: int,
) -> PDFSplitResult:
    if pages_per_part < 1:
        raise ValueError("Pages per part must be at least 1.")

    try:
        import fitz
    except ImportError as exc:
        raise PDFSplitError(
            "PDF splitting requires PyMuPDF. Install requirements.txt and restart the app."
        ) from exc

    try:
        source_doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PDFSplitError(f"Could not open PDF for splitting: {exc}") from exc

    try:
        total_pages = source_doc.page_count
        if total_pages < 1:
            raise PDFSplitError("PDF has no pages to split.")

        safe_name = safe_display_name(original_filename)
        stem = Path(safe_name).stem or "document"
        output_dir = output_root / f"pdf-parts-{uuid.uuid4().hex}"
        output_dir.mkdir(parents=True, exist_ok=True)

        part_count = math.ceil(total_pages / pages_per_part)
        parts: list[PDFPart] = []
        for part_index, start_page in enumerate(range(1, total_pages + 1, pages_per_part), start=1):
            end_page = min(start_page + pages_per_part - 1, total_pages)
            part_filename = f"{stem}-pages-{start_page:04d}-{end_page:04d}.pdf"
            part_path = output_dir / part_filename

            part_doc = fitz.open()
            try:
                part_doc.insert_pdf(source_doc, from_page=start_page - 1, to_page=end_page - 1)
                part_doc.save(part_path, garbage=4, deflate=True)
            finally:
                part_doc.close()

            parts.append(
                PDFPart(
                    file_path=part_path,
                    filename=part_filename,
                    page_start=start_page,
                    page_end=end_page,
                    page_count=end_page - start_page + 1,
                    part_index=part_index,
                    part_count=part_count,
                )
            )

        return PDFSplitResult(original_page_count=total_pages, parts=parts)
    finally:
        source_doc.close()
