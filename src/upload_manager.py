from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import TEMP_UPLOAD_DIR, format_api_error
from .file_search_manager import FileSearchManager, GeminiAPIError
from .validation import safe_display_name, validate_file


@dataclass(frozen=True)
class UploadResult:
    file_path: Path
    mime_type: str
    operation: Any
    final_operation: Any | None = None
    upload_strategy: str = "direct"
    operation_kind: str = "upload_to_file_search_store"
    file_name: str | None = None


class UploadManager:
    def __init__(
        self,
        client: Any,
        upload_dir: Path = TEMP_UPLOAD_DIR,
        secrets: Iterable[str | None] = (),
    ):
        self.client = client
        self.upload_dir = upload_dir
        self.secrets = tuple(secrets)
        self.file_search = FileSearchManager(client, secrets=secrets)

    def save_bytes(self, filename: str, data: bytes) -> Path:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_filename(filename)
        path = self.upload_dir / f"{uuid.uuid4().hex}-{safe_name}"
        path.write_bytes(data)
        return path

    def upload_file_bytes(
        self,
        file_search_store_name: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
        display_name: str | None = None,
        custom_metadata: list[dict[str, Any]] | None = None,
        wait: bool = True,
        poll_interval: float = 5.0,
        timeout_seconds: float = 600.0,
        upload_strategy: str = "files_api_import",
    ) -> UploadResult:
        validation = validate_file(filename, len(data), content_type, data=data)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors))

        file_path = self.save_bytes(filename, data)
        return self.upload_file_path(
            file_search_store_name=file_search_store_name,
            file_path=file_path,
            mime_type=validation.mime_type,
            display_name=display_name or safe_display_name(filename),
            custom_metadata=custom_metadata,
            wait=wait,
            poll_interval=poll_interval,
            timeout_seconds=timeout_seconds,
            upload_strategy=upload_strategy,
        )

    def upload_file_path(
        self,
        file_search_store_name: str,
        file_path: str | Path,
        mime_type: str | None = None,
        display_name: str | None = None,
        custom_metadata: list[dict[str, Any]] | None = None,
        wait: bool = True,
        poll_interval: float = 5.0,
        timeout_seconds: float = 600.0,
        upload_strategy: str = "files_api_import",
    ) -> UploadResult:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)

        data = path.read_bytes()
        validation = validate_file(path.name, len(data), mime_type, data=data)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors))

        config: dict[str, Any] = {
            "display_name": display_name or safe_display_name(path.name),
        }
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        if upload_strategy == "direct":
            return self._upload_direct(
                path=path,
                file_search_store_name=file_search_store_name,
                config=config,
                mime_type=validation.mime_type or "application/octet-stream",
                wait=wait,
                poll_interval=poll_interval,
                timeout_seconds=timeout_seconds,
            )
        return self._upload_via_files_api(
            path=path,
            file_search_store_name=file_search_store_name,
            display_name=display_name or safe_display_name(path.name),
            custom_metadata=custom_metadata,
            mime_type=validation.mime_type or "application/octet-stream",
            wait=wait,
            poll_interval=poll_interval,
            timeout_seconds=timeout_seconds,
        )

    def _upload_direct(
        self,
        path: Path,
        file_search_store_name: str,
        config: dict[str, Any],
        mime_type: str,
        wait: bool,
        poll_interval: float,
        timeout_seconds: float,
    ) -> UploadResult:
        try:
            operation = self.client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=file_search_store_name,
                file=str(path),
                config=config,
            )
            final_operation = None
            if wait:
                final_operation = self.file_search.wait_for_operation(
                    operation,
                    poll_interval=poll_interval,
                    timeout_seconds=timeout_seconds,
                )
            return UploadResult(
                file_path=path,
                mime_type=mime_type,
                operation=operation,
                final_operation=final_operation,
                upload_strategy="direct",
                operation_kind="upload_to_file_search_store",
            )
        except GeminiAPIError:
            raise
        except Exception as exc:
            raise GeminiAPIError(format_api_error(exc, self.secrets)) from None

    def _upload_via_files_api(
        self,
        path: Path,
        file_search_store_name: str,
        display_name: str,
        custom_metadata: list[dict[str, Any]] | None,
        mime_type: str,
        wait: bool,
        poll_interval: float,
        timeout_seconds: float,
    ) -> UploadResult:
        try:
            file_obj = self.client.files.upload(
                file=str(path),
                config={"display_name": display_name},
            )
            config: dict[str, Any] = {}
            if custom_metadata:
                config["custom_metadata"] = custom_metadata
            operation = self.client.file_search_stores.import_file(
                file_search_store_name=file_search_store_name,
                file_name=file_obj.name,
                config=config or None,
            )
            final_operation = None
            if wait:
                final_operation = self.file_search.wait_for_operation(
                    operation,
                    poll_interval=poll_interval,
                    timeout_seconds=timeout_seconds,
                )
            return UploadResult(
                file_path=path,
                mime_type=mime_type,
                operation=operation,
                final_operation=final_operation,
                upload_strategy="files_api_import",
                operation_kind="import_file",
                file_name=file_obj.name,
            )
        except GeminiAPIError:
            raise
        except Exception as exc:
            raise GeminiAPIError(format_api_error(exc, self.secrets)) from None


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "uploaded-file"
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:160]
