from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .validation import safe_display_name


SOURCE_ARCHIVE_DIR = Path(".source_files")
MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    original_filename: str
    stored_path: str
    mime_type: str
    size_bytes: int
    sha256: str
    file_search_store_name: str
    created_at: str
    document_name: str | None = None

    def to_file_search_metadata(self) -> list[dict[str, str]]:
        return [
            {"key": "source_id", "string_value": self.source_id},
            {"key": "source_filename", "string_value": self.original_filename},
            {"key": "source_sha256", "string_value": self.sha256},
        ]


class SourceRegistry:
    def __init__(self, base_dir: Path = SOURCE_ARCHIVE_DIR):
        self.base_dir = base_dir
        self.sources_dir = self.base_dir / "sources"
        self.manifest_path = self.base_dir / MANIFEST_FILENAME

    def save_source(
        self,
        filename: str,
        data: bytes,
        mime_type: str,
        file_search_store_name: str,
    ) -> SourceRecord:
        source_id = uuid.uuid4().hex
        display_name = safe_display_name(filename)
        target_dir = self.sources_dir / source_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / display_name
        target_path.write_bytes(data)

        record = SourceRecord(
            source_id=source_id,
            original_filename=display_name,
            stored_path=str(target_path.relative_to(self.base_dir)),
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            file_search_store_name=file_search_store_name,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        records = self.list_records()
        records.append(record)
        self._write_records(records)
        return record

    def list_records(self, file_search_store_name: str | None = None) -> list[SourceRecord]:
        raw = self._read_manifest()
        records = [SourceRecord(**item) for item in raw.get("sources", [])]
        if file_search_store_name:
            return [
                record
                for record in records
                if record.file_search_store_name == file_search_store_name
            ]
        return records

    def get(self, source_id: str | None) -> SourceRecord | None:
        if not source_id:
            return None
        for record in self.list_records():
            if record.source_id == source_id:
                return record
        return None

    def delete_source(self, source_id: str) -> bool:
        record = self.get(source_id)
        if record is None:
            return False

        records = [item for item in self.list_records() if item.source_id != source_id]
        self._write_records(records)

        source_dir = (self.sources_dir / source_id).resolve()
        base = self.base_dir.resolve()
        if base in source_dir.parents and source_dir.exists():
            shutil.rmtree(source_dir)
        return True

    def file_path(self, record: SourceRecord) -> Path:
        path = (self.base_dir / record.stored_path).resolve()
        base = self.base_dir.resolve()
        if base not in path.parents:
            raise ValueError("Stored source path is outside the configured source archive.")
        return path

    def file_bytes(self, record: SourceRecord) -> bytes:
        return self.file_path(record).read_bytes()

    def _read_manifest(self) -> dict[str, list[dict[str, object]]]:
        if not self.manifest_path.exists():
            return {"sources": []}
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"sources": []}
        if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
            return {"sources": []}
        return data

    def _write_records(self, records: list[SourceRecord]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        payload = {"sources": [asdict(record) for record in records]}
        tmp_path = self.manifest_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.manifest_path)


def source_id_from_custom_metadata(metadata: list[dict[str, object]] | None) -> str | None:
    if not metadata:
        return None
    for item in metadata:
        key = item.get("key")
        if key != "source_id":
            continue
        value = item.get("string_value") or item.get("stringValue")
        if isinstance(value, str):
            return value
    return None
