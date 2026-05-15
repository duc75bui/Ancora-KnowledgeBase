from types import SimpleNamespace

from src.citation_parser import (
    Citation,
    GroundingResult,
    GroundingSupportSpan,
    parse_grounding_metadata,
    search_entry_point_html,
    supplement_missing_citation_details,
)


def test_parse_grounding_metadata_from_dict():
    response = {
        "candidates": [
            {
                "groundingMetadata": {
                    "groundingChunks": [
                        {
                            "retrievedContext": {
                                "title": "handbook.pdf",
                                "text": "Policy text",
                                "fileSearchStore": "fileSearchStores/store-1",
                                "pageNumber": 4,
                                "mediaId": "fileSearchStores/store-1/media/blob-1",
                                "customMetadata": [{"key": "dept", "stringValue": "ops"}],
                            }
                        }
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"startIndex": 0, "endIndex": 11, "text": "Policy text"},
                            "groundingChunkIndices": [0],
                            "confidenceScores": [0.9],
                        }
                    ],
                }
            }
        ]
    }

    result = parse_grounding_metadata(response)

    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.title == "handbook.pdf"
    assert citation.page_number == 4
    assert citation.media_id == "fileSearchStores/store-1/media/blob-1"
    assert citation.custom_metadata == [{"key": "dept", "stringValue": "ops"}]
    assert result.grounding_supports
    assert result.support_spans[0].start_index == 0
    assert result.support_spans[0].end_index == 11
    assert result.support_spans[0].citation_indices == [0]


def test_parse_grounding_metadata_from_sdk_like_objects():
    retrieved_context = SimpleNamespace(title="image", media_id="media-1", page_number=None)
    chunk = SimpleNamespace(retrieved_context=retrieved_context)
    metadata = SimpleNamespace(grounding_chunks=[chunk], grounding_supports=[])
    candidate = SimpleNamespace(grounding_metadata=metadata)
    response = SimpleNamespace(candidates=[candidate], text="answer")

    result = parse_grounding_metadata(response)

    assert result.citations[0].title == "image"
    assert result.citations[0].media_id == "media-1"


def test_parse_google_search_web_grounding_metadata():
    response = {
        "candidates": [
            {
                "groundingMetadata": {
                    "searchEntryPoint": {"renderedContent": "<div>search suggestions</div>"},
                    "groundingChunks": [
                        {"web": {"uri": "https://example.com/source", "title": "Example Source"}}
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"startIndex": 0, "endIndex": 12, "text": "Web answer."},
                            "groundingChunkIndices": [0],
                        }
                    ],
                }
            }
        ]
    }

    result = parse_grounding_metadata(response)

    assert result.citations[0].title == "Example Source"
    assert result.citations[0].uri == "https://example.com/source"
    assert result.support_spans[0].citation_indices == [0]
    assert search_entry_point_html(response) == "<div>search suggestions</div>"


def test_supplement_missing_citation_details_preserves_review_pass_supports():
    reviewed = GroundingResult(
        citations=[Citation(title="manual.pdf", text="Reviewed snippet")],
        grounding_supports=[],
        support_spans=[
            GroundingSupportSpan(
                start_index=0,
                end_index=8,
                text="Reviewed",
                citation_indices=[0],
            )
        ],
        raw_grounding_metadata={"reviewed": True},
    )
    initial = GroundingResult(
        citations=[
            Citation(
                title="manual.pdf",
                text="Initial snippet",
                page_number=7,
                media_id="fileSearchStores/store/media/blob-1",
                custom_metadata=[{"key": "source_id", "stringValue": "source-1"}],
            )
        ],
        grounding_supports=[],
        support_spans=[],
        raw_grounding_metadata={"initial": True},
    )

    result = supplement_missing_citation_details(reviewed, initial)

    assert result.citations[0].text == "Reviewed snippet"
    assert result.citations[0].page_number == 7
    assert result.citations[0].media_id == "fileSearchStores/store/media/blob-1"
    assert result.citations[0].custom_metadata == [{"key": "source_id", "stringValue": "source-1"}]
    assert result.support_spans == reviewed.support_spans


def test_supplement_missing_citation_details_skips_ambiguous_title_matches():
    reviewed = GroundingResult(
        citations=[Citation(title="manual.pdf", text="Reviewed snippet")],
        grounding_supports=[],
        support_spans=[],
        raw_grounding_metadata=None,
    )
    initial = GroundingResult(
        citations=[
            Citation(title="manual.pdf", page_number=3),
            Citation(title="manual.pdf", page_number=9),
        ],
        grounding_supports=[],
        support_spans=[],
        raw_grounding_metadata=None,
    )

    result = supplement_missing_citation_details(reviewed, initial)

    assert result.citations[0].page_number is None


def test_supplement_missing_citation_details_can_fallback_by_index_for_review_pass():
    reviewed = GroundingResult(
        citations=[Citation(title="Reviewed source", text="Reviewed snippet")],
        grounding_supports=[],
        support_spans=[],
        raw_grounding_metadata=None,
    )
    initial = GroundingResult(
        citations=[
            Citation(
                title="manual.pdf",
                page_number=12,
                custom_metadata=[{"key": "source_id", "stringValue": "source-1"}],
            )
        ],
        grounding_supports=[],
        support_spans=[],
        raw_grounding_metadata=None,
    )

    result = supplement_missing_citation_details(
        reviewed,
        initial,
        allow_index_fallback=True,
    )

    assert result.citations[0].title == "Reviewed source"
    assert result.citations[0].page_number == 12
    assert result.citations[0].custom_metadata == [{"key": "source_id", "stringValue": "source-1"}]
