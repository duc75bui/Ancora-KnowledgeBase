from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import TEMP_UPLOAD_DIR, format_api_error, is_transient_api_error
from .file_search_manager import FileSearchManager, GeminiAPIError, OperationTimeoutError
from .validation import safe_display_name, validate_file


DEFAULT_TRANSIENT_RETRY_ATTEMPTS = 3
DEFAULT_TRANSIENT_RETRY_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class UploadResult:
    file_path: Path
    mime_type: str
    operation: Any
    final_operation: Any | None = None
    upload_strategy: str = "direct"
    operation_kind: str = "upload_to_file_search_store"
    file_name: str | None = None


class UploadStageError(GeminiAPIError):
    def __init__(
        self,
        stage: str,
        message: str,
        attempts: int,
        retryable: bool,
    ):
        retry_note = (
            " Google returned a transient server-side error and the app exhausted "
            "its retry attempts."
            if retryable
            else ""
        )
        super().__init__(f"{stage} failed after {attempts} attempt(s).{retry_note}\n\n{message}")
        self.stage = stage
        self.attempts = attempts
        self.retryable = retryable


class UploadManager:
    def __init__(
        self,
        client: Any,
        upload_dir: Path = TEMP_UPLOAD_DIR,
        secrets: Iterable[str | None] = (),
        retry_attempts: int = DEFAULT_TRANSIENT_RETRY_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_TRANSIENT_RETRY_DELAY_SECONDS,
    ):
        self.client = client
        self.upload_dir = upload_dir
        self.secrets = tuple(secrets)
        self.retry_attempts = max(1, retry_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
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
            operation = self._call_with_transient_retries(
                "Direct File Search upload",
                self.client.file_search_stores.upload_to_file_search_store,
                file_search_store_name=file_search_store_name,
                file=str(path),
                config=config,
            )
            final_operation = None
            if wait:
                try:
                    final_operation = self.file_search.wait_for_operation(
                        operation,
                        poll_interval=poll_interval,
                        timeout_seconds=timeout_seconds,
                    )
                except OperationTimeoutError:
                    raise
                except GeminiAPIError as exc:
                    raise UploadStageError(
                        "Direct File Search import status polling",
                        str(exc),
                        attempts=1,
                        retryable=is_transient_api_error(exc),
                    ) from None
            return UploadResult(
                file_path=path,
                mime_type=mime_type,
                operation=operation,
                final_operation=final_operation,
                upload_strategy="direct",
                operation_kind="upload_to_file_search_store",
            )
        except UploadStageError:
            raise
        except GeminiAPIError:
            raise
        except Exception as exc:
            raise UploadStageError(
                "Direct File Search upload",
                format_api_error(exc, self.secrets),
                attempts=1,
                retryable=is_transient_api_error(exc),
            ) from None

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
        file_name = None
        try:
            file_obj = self._call_with_transient_retries(
                "Files API upload",
                self.client.files.upload,
                file=str(path),
                config={"display_name": display_name},
            )
            file_name = file_obj.name
            config: dict[str, Any] = {}
            if custom_metadata:
                config["custom_metadata"] = custom_metadata
            operation = self._call_with_transient_retries(
                "File Search import",
                self.client.file_search_stores.import_file,
                file_search_store_name=file_search_store_name,
                file_name=file_name,
                config=config or None,
            )
            final_operation = None
            if wait:
                try:
                    final_operation = self.file_search.wait_for_operation(
                        operation,
                        poll_interval=poll_interval,
                        timeout_seconds=timeout_seconds,
                    )
                except OperationTimeoutError:
                    raise
                except GeminiAPIError as exc:
                    raise UploadStageError(
                        "File Search import status polling",
                        str(exc),
                        attempts=1,
                        retryable=is_transient_api_error(exc),
                    ) from None
            return UploadResult(
                file_path=path,
                mime_type=mime_type,
                operation=operation,
                final_operation=final_operation,
                upload_strategy="files_api_import",
                operation_kind="import_file",
                file_name=file_name,
            )
        except UploadStageError:
            raise
        except GeminiAPIError:
            raise
        except Exception as exc:
            stage = "File Search import" if file_name else "Files API upload"
            raise UploadStageError(
                stage,
                format_api_error(exc, self.secrets),
                attempts=1,
                retryable=is_transient_api_error(exc),
            ) from None

    def _call_with_transient_retries(
        self,
        stage: str,
        func: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        last_error = ""
        last_retryable = False
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                last_error = format_api_error(exc, self.secrets)
                last_retryable = is_transient_api_error(last_error)
                if not last_retryable or attempt >= self.retry_attempts:
                    raise UploadStageError(
                        stage,
                        last_error,
                        attempts=attempt,
                        retryable=last_retryable,
                    ) from None
                time.sleep(self.retry_delay_seconds * (2 ** (attempt - 1)))

        raise UploadStageError(
            stage,
            last_error or "Unknown upload/import error.",
            attempts=self.retry_attempts,
            retryable=last_retryable,
        )


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "uploaded-file"
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:160]
