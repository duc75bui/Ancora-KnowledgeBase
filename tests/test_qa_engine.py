from types import SimpleNamespace

import pytest

from src.file_search_manager import GeminiAPIError
from src.qa_engine import QAEngine, QueryImage


class FakeModels:
    def __init__(self):
        self.call = None

    def generate_content(self, *, model, contents, config):
        self.call = (model, contents, config)
        grounding = SimpleNamespace(
            grounding_chunks=[
                SimpleNamespace(
                    retrieved_context=SimpleNamespace(
                        title="doc.txt",
                        text="Grounded text",
                        file_search_store="fileSearchStores/store-1",
                        page_number=1,
                    )
                )
            ],
            grounding_supports=[],
        )
        return SimpleNamespace(text="Grounded answer", candidates=[SimpleNamespace(grounding_metadata=grounding)])


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


def test_query_uses_only_file_search_tool_for_selected_store():
    client = FakeClient()
    engine = QAEngine(client)

    result = engine.answer(
        question="What is the policy?",
        model="gemini-3-flash-preview",
        file_search_store_name="fileSearchStores/store-1",
    )

    model, contents, config = client.models.call
    assert model == "gemini-3-flash-preview"
    assert contents == "What is the policy?"
    assert len(config.tools) == 1
    assert config.tools[0].file_search.file_search_store_names == ["fileSearchStores/store-1"]
    assert config.tools[0].google_search is None
    assert config.tools[0].url_context is None
    assert result.text == "Grounded answer"
    assert result.grounding.citations[0].title == "doc.txt"


def test_query_can_include_inline_image_context():
    client = FakeClient()
    engine = QAEngine(client)

    engine.answer(
        question="What store policy applies to this screenshot?",
        model="gemini-3-flash-preview",
        file_search_store_name="fileSearchStores/store-1",
        query_images=[
            QueryImage(
                filename="screen.png",
                data=b"\x89PNG\r\n\x1a\nimage",
                mime_type="image/png",
            )
        ],
    )

    _, contents, _ = client.models.call
    assert isinstance(contents, list)
    assert contents[0].inline_data.mime_type == "image/png"
    assert contents[0].inline_data.data == b"\x89PNG\r\n\x1a\nimage"
    assert contents[1] == "What store policy applies to this screenshot?"


def test_query_api_errors_are_sanitized():
    secret = "test-secret-123456"

    class BrokenModels:
        def generate_content(self, *, model, contents, config):
            raise RuntimeError(f"bad API key {secret}")

    client = SimpleNamespace(models=BrokenModels())
    engine = QAEngine(client, secrets=[secret])

    with pytest.raises(GeminiAPIError) as exc:
        engine.answer("Question", "gemini-3-flash-preview", "fileSearchStores/store-1")

    assert secret not in str(exc.value)
