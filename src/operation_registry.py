from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import APP_CONFIG_DIR


PENDING_OPERATIONS_PATH = APP_CONFIG_DIR / "pending_operations.json"


@dataclass(frozen=True)
class PendingOperationRecord:
    operation_name: str
    operation_kind: str
    file_search_store_name: str
    filename: str
    source_id: str | None
    upload_strategy: str
    created_at: str
    updated_at: str
    file_name: str | None = None
    status: dict[str, Any] | None = None
    done: bool = False


class OperationRegistry:
    def __init__(self, path: Path = PENDING_OPERATIONS_PATH):
        self.path = path

    def upsert(
        self,
        operation_name: str,
        operation_kind: str,
        file_search_store_name: str,
        filename: str,
        source_id: str | None,
        upload_strategy: str,
        file_name: str | None = None,
        status: dict[str, Any] | None = None,
        done: bool = False,
    ) -> PendingOperationRecord:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get(operation_name)
        record = PendingOperationRecord(
            operation_name=operation_name,
            operation_kind=operation_kind,
            file_search_store_name=file_search_store_name,
            filename=filename,
            source_id=source_id,
            upload_strategy=upload_strategy,
            file_name=file_name if file_name is not None else (existing.file_name if existing else None),
            created_at=existing.created_at if existing else now,
            updated_at=now,
            status=status,
            done=done,
        )
        records = [item for item in self.list_records() if item.operation_name != operation_name]
        records.append(record)
        self._write_records(records)
        return record

    def list_records(self, file_search_store_name: str | None = None) -> list[PendingOperationRecord]:
        raw = self._read()
        records = [PendingOperationRecord(**item) for item in raw.get("operations", [])]
        records.sort(key=lambda record: record.created_at, reverse=True)
        if file_search_store_name:
            return [
                record
                for record in records
                if record.file_search_store_name == file_search_store_name
            ]
        return records

    def get(self, operation_name: str) -> PendingOperationRecord | None:
        for record in self.list_records():
            if record.operation_name == operation_name:
                return record
        return None

    def delete(self, operation_name: str) -> bool:
        records = [record for record in self.list_records() if record.operation_name != operation_name]
        if len(records) == len(self.list_records()):
            return False
        self._write_records(records)
        return True

    def clear_completed(self) -> int:
        records = self.list_records()
        remaining = [record for record in records if not record.done]
        removed = len(records) - len(remaining)
        if removed:
            self._write_records(remaining)
        return removed

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"operations": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"operations": []}
        if not isinstance(data, dict) or not isinstance(data.get("operations"), list):
            return {"operations": []}
        return data

    def _write_records(self, records: list[PendingOperationRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"operations": [asdict(record) for record in records]}
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)
