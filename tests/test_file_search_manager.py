from types import SimpleNamespace

import pytest

from src.file_search_manager import FileSearchManager, GeminiAPIError


class FakeFileSearchStores:
    def __init__(self):
        self.created_config = None
        self.import_args = None
        self.deleted_store = None
        self.documents = FakeDocuments()
        self.uploaded = None

    def create(self, *, config=None):
        self.created_config = config
        return SimpleNamespace(name="fileSearchStores/store-1", display_name=config["display_name"])

    def list(self, *, config=None):
        return [SimpleNamespace(name="fileSearchStores/store-1")]

    def delete(self, *, name, config=None):
        self.deleted_store = (name, config)

    def import_file(self, *, file_search_store_name, file_name, config=None):
        self.import_args = (file_search_store_name, file_name, config)
        return SimpleNamespace(name="operations/import-1", done=True)

    def upload_to_file_search_store(self, *, file_search_store_name, file, config=None):
        self.uploaded = (file_search_store_name, file, config)
        return SimpleNamespace(name="operations/upload-1", done=True)

    def download_media(self, *, media_id, config=None):
        return b"image-bytes"


class FakeDocuments:
    def __init__(self):
        self.deleted = None

    def list(self, *, parent, config=None):
        return [SimpleNamespace(name=f"{parent}/documents/doc-1")]

    def get(self, *, name, config=None):
        return SimpleNamespace(name=name)

    def delete(self, *, name, config=None):
        self.deleted = (name, config)


class FakeClient:
    def __init__(self):
        self.file_search_stores = FakeFileSearchStores()
        self.operations = SimpleNamespace(get=lambda operation: operation)


def test_create_store_uses_multimodal_embedding_model():
    client = FakeClient()
    manager = FileSearchManager(client)

    store = manager.create_store("Knowledge Base")

    assert store.name == "fileSearchStores/store-1"
    assert client.file_search_stores.created_config == {
        "display_name": "Knowledge Base",
        "embedding_model": "models/gemini-embedding-2",
    }


def test_import_file_calls_google_file_search_import_api():
    client = FakeClient()
    manager = FileSearchManager(client)

    operation = manager.import_file("fileSearchStores/store-1", "files/file-1")

    assert operation.done is True
    assert client.file_search_stores.import_args == ("fileSearchStores/store-1", "files/file-1", None)


def test_list_and_delete_documents():
    client = FakeClient()
    manager = FileSearchManager(client)

    docs = manager.list_documents("fileSearchStores/store-1")
    manager.delete_document(docs[0].name, force=True)

    assert docs[0].name == "fileSearchStores/store-1/documents/doc-1"
    assert client.file_search_stores.documents.deleted == (
        "fileSearchStores/store-1/documents/doc-1",
        {"force": True},
    )


def test_api_errors_are_sanitized():
    secret = "test-secret-123456"

    class BrokenStores(FakeFileSearchStores):
        def list(self, *, config=None):
            raise RuntimeError(f"bad API key {secret}")

    client = FakeClient()
    client.file_search_stores = BrokenStores()
    manager = FileSearchManager(client, secrets=[secret])

    with pytest.raises(GeminiAPIError) as exc:
        manager.list_stores()

    assert secret not in str(exc.value)
    assert "test...3456" in str(exc.value)
