from types import SimpleNamespace

from src.citation_parser import parse_grounding_metadata


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
                    "groundingSupports": [{"segment": {"startIndex": 0}}],
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


def test_parse_grounding_metadata_from_sdk_like_objects():
    retrieved_context = SimpleNamespace(title="image", media_id="media-1", page_number=None)
    chunk = SimpleNamespace(retrieved_context=retrieved_context)
    metadata = SimpleNamespace(grounding_chunks=[chunk], grounding_supports=[])
    candidate = SimpleNamespace(grounding_metadata=metadata)
    response = SimpleNamespace(candidates=[candidate], text="answer")

    result = parse_grounding_metadata(response)

    assert result.citations[0].title == "image"
    assert result.citations[0].media_id == "media-1"
