from types import SimpleNamespace

from src.upload_manager import UploadManager


class FakeStores:
    def __init__(self):
        self.uploaded = None

    def upload_to_file_search_store(self, *, file_search_store_name, file, config=None):
        self.uploaded = (file_search_store_name, file, config)
        return SimpleNamespace(name="operations/upload-1", done=True)


class FakeClient:
    def __init__(self):
        self.file_search_stores = FakeStores()
        self.operations = SimpleNamespace(get=lambda operation: operation)


def test_upload_file_bytes_calls_google_upload_to_store(tmp_path):
    client = FakeClient()
    manager = UploadManager(client, upload_dir=tmp_path)

    result = manager.upload_file_bytes(
        file_search_store_name="fileSearchStores/store-1",
        filename="notes.txt",
        data=b"hello",
        content_type="text/plain",
        custom_metadata=[{"key": "source_id", "string_value": "source-1"}],
        wait=True,
    )

    store_name, uploaded_path, config = client.file_search_stores.uploaded
    assert store_name == "fileSearchStores/store-1"
    assert uploaded_path.endswith("notes.txt")
    assert config["display_name"] == "notes.txt"
    assert config["mime_type"] == "text/plain"
    assert config["custom_metadata"] == [{"key": "source_id", "string_value": "source-1"}]
    assert result.final_operation.done is True
