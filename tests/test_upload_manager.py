from types import SimpleNamespace

import pytest

from src.upload_manager import UploadManager, UploadStageError


class FakeStores:
    def __init__(self):
        self.uploaded = None
        self.imported = None

    def upload_to_file_search_store(self, *, file_search_store_name, file, config=None):
        self.uploaded = (file_search_store_name, file, config)
        return SimpleNamespace(name="operations/upload-1", done=True)

    def import_file(self, *, file_search_store_name, file_name, config=None):
        self.imported = (file_search_store_name, file_name, config)
        return SimpleNamespace(name="operations/import-1", done=True)


class FakeFiles:
    def __init__(self):
        self.uploaded = None

    def upload(self, *, file, config=None):
        self.uploaded = (file, config)
        return SimpleNamespace(name="files/file-1")


class FakeClient:
    def __init__(self):
        self.file_search_stores = FakeStores()
        self.files = FakeFiles()
        self.operations = SimpleNamespace(get=lambda operation: operation)


class FlakyImportStores(FakeStores):
    def __init__(self, failures_before_success: int):
        super().__init__()
        self.failures_before_success = failures_before_success
        self.import_attempts = 0

    def import_file(self, *, file_search_store_name, file_name, config=None):
        self.import_attempts += 1
        if self.import_attempts <= self.failures_before_success:
            raise RuntimeError("500 INTERNAL. Internal error encountered.")
        return super().import_file(
            file_search_store_name=file_search_store_name,
            file_name=file_name,
            config=config,
        )


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
        upload_strategy="direct",
    )

    store_name, uploaded_path, config = client.file_search_stores.uploaded
    assert store_name == "fileSearchStores/store-1"
    assert uploaded_path.endswith("notes.txt")
    assert config["display_name"] == "notes.txt"
    assert "mime_type" not in config
    assert config["custom_metadata"] == [{"key": "source_id", "string_value": "source-1"}]
    assert result.final_operation.done is True
    assert result.upload_strategy == "direct"
    assert result.operation_kind == "upload_to_file_search_store"


def test_upload_file_bytes_can_use_files_api_then_import(tmp_path):
    client = FakeClient()
    manager = UploadManager(client, upload_dir=tmp_path)

    result = manager.upload_file_bytes(
        file_search_store_name="fileSearchStores/store-1",
        filename="manual.pdf",
        data=b"%PDF data",
        content_type="application/pdf",
        custom_metadata=[{"key": "source_id", "string_value": "source-1"}],
        wait=True,
    )

    uploaded_path, upload_config = client.files.uploaded
    assert uploaded_path.endswith("manual.pdf")
    assert upload_config["display_name"] == "manual.pdf"
    assert client.file_search_stores.imported == (
        "fileSearchStores/store-1",
        "files/file-1",
        {"custom_metadata": [{"key": "source_id", "string_value": "source-1"}]},
    )
    assert result.operation.name == "operations/import-1"
    assert result.upload_strategy == "files_api_import"
    assert result.operation_kind == "import_file"
    assert result.file_name == "files/file-1"


def test_upload_file_bytes_retries_transient_import_errors(tmp_path):
    client = FakeClient()
    client.file_search_stores = FlakyImportStores(failures_before_success=1)
    manager = UploadManager(client, upload_dir=tmp_path, retry_delay_seconds=0)

    result = manager.upload_file_bytes(
        file_search_store_name="fileSearchStores/store-1",
        filename="manual.pdf",
        data=b"%PDF data",
        content_type="application/pdf",
        wait=True,
    )

    assert client.file_search_stores.import_attempts == 2
    assert result.operation.name == "operations/import-1"


def test_upload_file_bytes_reports_stage_after_transient_retries_exhausted(tmp_path):
    client = FakeClient()
    client.file_search_stores = FlakyImportStores(failures_before_success=3)
    manager = UploadManager(
        client,
        upload_dir=tmp_path,
        retry_attempts=2,
        retry_delay_seconds=0,
    )

    with pytest.raises(UploadStageError) as exc:
        manager.upload_file_bytes(
            file_search_store_name="fileSearchStores/store-1",
            filename="manual.pdf",
            data=b"%PDF data",
            content_type="application/pdf",
            wait=True,
        )

    assert exc.value.stage == "File Search import"
    assert exc.value.retryable is True
    assert exc.value.attempts == 2
