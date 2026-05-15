from src.citation_parser import Citation
from src.source_registry import SourceRegistry

from app import citation_source_view_links, citation_source_view_targets


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

    assert links[record.source_id] == f"?source_id={record.source_id}&page=4&answer_id=answer-1"


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
