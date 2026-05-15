import fitz

from src.pdf_preview import render_pdf_page_png


def test_render_pdf_page_png_returns_requested_page_image():
    document = fitz.open()
    for page_number in range(1, 3):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {page_number}")
    data = document.tobytes()
    document.close()

    preview = render_pdf_page_png(data, page_number=2, zoom=0.5)

    assert preview.page_number == 2
    assert preview.page_count == 2
    assert preview.png_bytes.startswith(b"\x89PNG")


def test_render_pdf_page_png_clamps_out_of_range_page():
    document = fitz.open()
    document.new_page()
    data = document.tobytes()
    document.close()

    preview = render_pdf_page_png(data, page_number=99, zoom=0.5)

    assert preview.page_number == 1
    assert preview.page_count == 1
