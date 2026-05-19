from src.citation_parser import Citation
from src.source_registry import SourceRegistry

from app import (
    citation_original_page_number,
    citation_source_link_key,
    citation_source_view_links,
    citation_source_view_targets,
    pdf_part_file_search_metadata,
)
from src.pdf_splitter import PDFPart


def test_citation_source_view_links_match_archived_pdf_by_source_id(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="Manual.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
    )

    links = citation_source_view_links(
        registry,
        [
            Citation(
                title="Manual.pdf",
                page_number=4,
                custom_metadata=[{"key": "source_id", "string_value": record.source_id}],
            )
        ],
        "fileSearchStores/store-1",
    )

    exact_key = citation_source_link_key("source_id", record.source_id, 4)
    title_key = citation_source_link_key("title", "Manual.pdf", 4)
    assert links[exact_key] == f"?source_id={record.source_id}&page=4"
    assert links[title_key] == f"?source_id={record.source_id}&page=4"
    assert links[record.source_id] == f"?source_id={record.source_id}&page=4"
    assert links["Manual.pdf"] == f"?source_id={record.source_id}&page=4"


def test_citation_source_view_links_can_preserve_answer_id(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="Manual.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
    )

    links = citation_source_view_links(
        registry,
        [
            Citation(
                title="Manual.pdf",
                page_number=4,
                custom_metadata=[{"key": "source_id", "string_value": record.source_id}],
            )
        ],
        "fileSearchStores/store-1",
        answer_id="answer-1",
    )

    exact_key = citation_source_link_key("source_id", record.source_id, 4)
    assert links[exact_key] == f"?source_id={record.source_id}&page=4&answer_id=answer-1"


def test_citation_source_view_links_keep_distinct_pages_for_same_pdf(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="Manual.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
    )

    links = citation_source_view_links(
        registry,
        [
            Citation(
                title="Manual.pdf",
                page_number=4,
                custom_metadata=[{"key": "source_id", "string_value": record.source_id}],
            ),
            Citation(
                title="Manual.pdf",
                page_number=9,
                custom_metadata=[{"key": "source_id", "string_value": record.source_id}],
            ),
        ],
        "fileSearchStores/store-1",
    )

    page_4_key = citation_source_link_key("source_id", record.source_id, 4)
    page_9_key = citation_source_link_key("source_id", record.source_id, 9)
    assert links[page_4_key] == f"?source_id={record.source_id}&page=4"
    assert links[page_9_key] == f"?source_id={record.source_id}&page=9"


def test_citation_source_view_targets_match_archived_pdf_by_title_stem(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="System Architecture.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
    )

    targets = citation_source_view_targets(
        registry,
        [Citation(title="System Architecture", page_number=2)],
        "fileSearchStores/store-1",
    )

    assert targets == [
        {
            "citation_index": 1,
            "source_id": record.source_id,
            "title": "System Architecture - page 2",
            "page_number": 2,
        }
    ]


def test_split_pdf_citation_links_map_part_page_to_original_page(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="Manual.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
    )
    citation = Citation(
        title="Manual-pages-0026-0050.pdf",
        page_number=3,
        custom_metadata=[
            {"key": "source_id", "string_value": record.source_id},
            {"key": "source_page_start", "numeric_value": 26},
            {"key": "source_page_end", "numeric_value": 50},
        ],
    )

    links = citation_source_view_links(registry, [citation], "fileSearchStores/store-1")
    targets = citation_source_view_targets(registry, [citation], "fileSearchStores/store-1")

    assert citation_original_page_number(citation) == 28
    assert links[citation_source_link_key("source_id", record.source_id, 3)] == (
        f"?source_id={record.source_id}&page=28"
    )
    assert targets[0]["page_number"] == 28


def test_pdf_part_metadata_keeps_original_source_and_page_range(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="Manual.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
        custom_metadata=[{"key": "department", "string_value": "Support"}],
    )
    part = PDFPart(
        file_path=tmp_path / "Manual-pages-0001-0025.pdf",
        filename="Manual-pages-0001-0025.pdf",
        page_start=1,
        page_end=25,
        page_count=25,
        part_index=1,
        part_count=3,
    )

    metadata = pdf_part_file_search_metadata(record, part)

    assert {"key": "source_id", "string_value": record.source_id} in metadata
    assert {"key": "source_filename", "string_value": "Manual.pdf"} in metadata
    assert {"key": "source_page_start", "numeric_value": 1} in metadata
    assert {"key": "source_page_end", "numeric_value": 25} in metadata
    assert {"key": "department", "string_value": "Support"} in metadata
