from src.operation_registry import OperationRegistry


def test_operation_registry_upserts_and_filters_records(tmp_path):
    registry = OperationRegistry(tmp_path / "pending_operations.json")

    registry.upsert(
        operation_name="operations/import-1",
        operation_kind="import_file",
        file_search_store_name="fileSearchStores/store-1",
        filename="manual.pdf",
        source_id="source-1",
        upload_strategy="files_api_import",
        file_name="files/file-1",
        status={"done": False},
    )
    registry.upsert(
        operation_name="operations/import-2",
        operation_kind="import_file",
        file_search_store_name="fileSearchStores/store-2",
        filename="other.pdf",
        source_id="source-2",
        upload_strategy="files_api_import",
        status={"done": False},
    )

    records = registry.list_records("fileSearchStores/store-1")

    assert len(records) == 1
    assert records[0].operation_name == "operations/import-1"
    assert records[0].file_name == "files/file-1"


def test_operation_registry_updates_status_and_clears_completed(tmp_path):
    registry = OperationRegistry(tmp_path / "pending_operations.json")
    registry.upsert(
        operation_name="operations/import-1",
        operation_kind="import_file",
        file_search_store_name="fileSearchStores/store-1",
        filename="manual.pdf",
        source_id="source-1",
        upload_strategy="files_api_import",
        status={"done": False},
    )
    registry.upsert(
        operation_name="operations/import-1",
        operation_kind="import_file",
        file_search_store_name="fileSearchStores/store-1",
        filename="manual.pdf",
        source_id="source-1",
        upload_strategy="files_api_import",
        status={"done": True},
        done=True,
    )

    assert registry.get("operations/import-1").done is True
    assert registry.clear_completed() == 1
    assert registry.list_records() == []
