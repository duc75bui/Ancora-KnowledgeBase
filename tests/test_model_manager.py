from types import SimpleNamespace

import pytest

from src.config import SUPPORTED_FILE_SEARCH_MODELS
from src.model_manager import (
    ModelManager,
    default_model_from,
    normalize_model_id,
    supports_generate_content,
)


def test_approved_models_include_documented_defaults(tmp_path):
    manager = ModelManager(tmp_path / "models.json")

    approved = manager.approved_models()

    assert approved == SUPPORTED_FILE_SEARCH_MODELS


def test_approve_and_remove_model_persists_to_config(tmp_path):
    manager = ModelManager(tmp_path / "models.json")

    manager.approve_model("models/gemini-new-preview", "Gemini New Preview")

    assert manager.approved_models()["gemini-new-preview"] == "Gemini New Preview"

    manager.remove_approved_model("gemini-new-preview")

    assert "gemini-new-preview" not in manager.approved_models()


def test_refresh_from_client_filters_generate_content_models(tmp_path):
    class FakeModels:
        def list(self, *, config=None):
            return [
                SimpleNamespace(
                    name="models/gemini-new-preview",
                    display_name="Gemini New Preview",
                    supported_actions=["generateContent"],
                ),
                SimpleNamespace(
                    name="models/embedding-only",
                    display_name="Embedding Only",
                    supported_actions=["embedContent"],
                ),
                SimpleNamespace(
                    name="publishers/google/models/gemini-invalid",
                    display_name="Invalid Name Shape",
                    supported_actions=["generateContent"],
                ),
            ]

    client = SimpleNamespace(models=FakeModels())
    manager = ModelManager(tmp_path / "models.json")

    discovered = manager.refresh_from_client(client)

    assert discovered[0].model_id == "gemini-new-preview"
    assert manager.discovered_models()[0].display_name == "Gemini New Preview"
    assert len(discovered) == 1


def test_normalize_model_id_accepts_gemini_model_names():
    assert normalize_model_id("models/gemini-3-flash-preview") == "gemini-3-flash-preview"
    assert normalize_model_id("gemini-3.1-pro-preview") == "gemini-3.1-pro-preview"
    assert normalize_model_id("text-embedding-004") is None


def test_supports_generate_content_reads_sdk_like_objects():
    model = SimpleNamespace(supported_actions=["generateContent"])

    assert supports_generate_content(model)
    assert not supports_generate_content(SimpleNamespace(supported_actions=["embedContent"]))


def test_default_model_from_uses_available_default_or_first():
    assert default_model_from({"gemini-3-flash-preview": "Gemini"}) == "gemini-3-flash-preview"
    assert default_model_from({"gemini-other": "Gemini Other"}) == "gemini-other"


def test_approve_model_rejects_invalid_id(tmp_path):
    manager = ModelManager(tmp_path / "models.json")

    with pytest.raises(ValueError):
        manager.approve_model("text-embedding-004")
