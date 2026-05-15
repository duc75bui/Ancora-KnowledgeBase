from types import SimpleNamespace

import pytest

from src.file_search_manager import GeminiAPIError
from src.qa_engine import QAEngine, QueryImage, build_review_prompt, build_system_instruction


class FakeModels:
    def __init__(self):
        self.call = None
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.call = (model, contents, config)
        self.calls.append(self.call)
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
    assert "balanced level of detail" in config.system_instruction


def test_query_can_include_metadata_filter_and_top_k():
    client = FakeClient()
    engine = QAEngine(client)

    engine.answer(
        question="What is the policy?",
        model="gemini-3-flash-preview",
        file_search_store_name="fileSearchStores/store-1",
        metadata_filter='department = "Operations"',
        top_k=8,
    )

    _, _, config = client.models.call
    file_search = config.tools[0].file_search
    assert file_search.metadata_filter == 'department = "Operations"'
    assert file_search.top_k == 8


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


def test_web_query_uses_google_search_tool_not_file_search():
    client = FakeClient()
    engine = QAEngine(client)

    engine.answer_web(
        question="Who won the latest major product award?",
        model="gemini-3-flash-preview",
        answer_style="Very deep technical",
    )

    _, contents, config = client.models.call
    assert contents == "Who won the latest major product award?"
    assert len(config.tools) == 1
    assert config.tools[0].google_search is not None
    assert config.tools[0].file_search is None
    assert "deep technical answer" in config.system_instruction


def test_reverify_answer_uses_file_search_tool_and_review_prompt():
    client = FakeClient()
    engine = QAEngine(client)

    result = engine.reverify_answer(
        question="What is the policy?",
        draft_answer="The policy is X.",
        model="gemini-3-flash-preview",
        file_search_store_name="fileSearchStores/store-1",
        metadata_filter='department = "Operations"',
        top_k=5,
        answer_style="Concise",
    )

    model, contents, config = client.models.call
    assert model == "gemini-3-flash-preview"
    assert "Initial answer to review" in contents
    assert "The policy is X." in contents
    assert config.tools[0].file_search.file_search_store_names == ["fileSearchStores/store-1"]
    assert config.tools[0].file_search.metadata_filter == 'department = "Operations"'
    assert config.tools[0].file_search.top_k == 5
    assert config.tools[0].google_search is None
    assert "source-grounded review pass" in config.system_instruction
    assert "Be concise" in config.system_instruction
    assert result.text == "Grounded answer"


def test_build_review_prompt_includes_question_and_draft():
    prompt = build_review_prompt("Question?", "Draft answer.")

    assert "Question?" in prompt
    assert "Draft answer." in prompt
    assert "Return the final answer only" in prompt


def test_build_system_instruction_falls_back_to_balanced_style():
    instruction = build_system_instruction("Base", "Unknown")

    assert instruction.startswith("Base")
    assert "balanced level of detail" in instruction


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
