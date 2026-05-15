from types import SimpleNamespace

from src.citation_parser import parse_grounding_metadata, search_entry_point_html


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
