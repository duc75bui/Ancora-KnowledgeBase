from src.source_registry import SourceRegistry, source_id_from_custom_metadata


def test_source_registry_saves_metadata_and_file(tmp_path):
    registry = SourceRegistry(tmp_path)

    record = registry.save_source(
        filename="policy.pdf",
        data=b"%PDF data",
        mime_type="application/pdf",
        file_search_store_name="fileSearchStores/store-1",
    )

    assert registry.get(record.source_id) == record
    assert registry.file_bytes(record) == b"%PDF data"
    assert registry.list_records("fileSearchStores/store-1") == [record]
    assert registry.list_records("fileSearchStores/other") == []

    metadata = record.to_file_search_metadata()
    assert source_id_from_custom_metadata(metadata) == record.source_id


def test_source_registry_deletes_file_and_manifest_record(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="notes.txt",
        data=b"hello",
        mime_type="text/plain",
        file_search_store_name="fileSearchStores/store-1",
    )

    assert registry.delete_source(record.source_id)

    assert registry.get(record.source_id) is None
    assert not (tmp_path / "sources" / record.source_id).exists()


def test_source_id_from_camel_case_metadata():
    assert source_id_from_custom_metadata([{"key": "source_id", "stringValue": "abc"}]) == "abc"


def test_find_by_filename_matches_single_record_in_store(tmp_path):
    registry = SourceRegistry(tmp_path)
    record = registry.save_source(
        filename="Deployment Diagram 2.png",
        data=b"\x89PNG\r\n\x1a\nimage",
        mime_type="image/png",
        file_search_store_name="fileSearchStores/store-1",
    )
    registry.save_source(
        filename="Deployment Diagram 2.png",
        data=b"\x89PNG\r\n\x1a\nimage",
        mime_type="image/png",
        file_search_store_name="fileSearchStores/store-2",
    )

    assert registry.find_by_filename("deployment diagram 2.PNG", "fileSearchStores/store-1") == record


def test_find_by_filename_returns_none_for_ambiguous_matches(tmp_path):
    registry = SourceRegistry(tmp_path)
    for _ in range(2):
        registry.save_source(
            filename="diagram.png",
            data=b"\x89PNG\r\n\x1a\nimage",
            mime_type="image/png",
            file_search_store_name="fileSearchStores/store-1",
        )

    assert registry.find_by_filename("diagram.png", "fileSearchStores/store-1") is None
