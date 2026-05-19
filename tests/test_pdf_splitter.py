import fitz

from src.pdf_splitter import split_pdf_bytes


def test_split_pdf_bytes_creates_page_range_parts(tmp_path):
    document = fitz.open()
    for page_number in range(1, 6):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {page_number}")
    data = document.tobytes()
    document.close()

    result = split_pdf_bytes(
        data=data,
        original_filename="Manual.pdf",
        output_root=tmp_path,
        pages_per_part=2,
    )

    assert result.original_page_count == 5
    assert [(part.page_start, part.page_end) for part in result.parts] == [
        (1, 2),
        (3, 4),
        (5, 5),
    ]
    assert all(part.file_path.exists() for part in result.parts)
    assert result.parts[0].filename == "Manual-pages-0001-0002.pdf"
