from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .citation_parser import to_plain_data
from .config import FILE_SEARCH_EMBEDDING_MODEL, format_api_error


class GeminiAPIError(RuntimeError):
    pass


class OperationTimeoutError(GeminiAPIError):
    pass


@dataclass(frozen=True)
class OperationStatus:
    name: str | None
    done: bool
    error: Any = None
    response: Any = None
    metadata: Any = None


class FileSearchManager:
    def __init__(self, client: Any, secrets: Iterable[str | None] = ()):
        self.client = client
        self.secrets = tuple(secrets)

    def create_store(
        self,
        display_name: str,
        embedding_model: str = FILE_SEARCH_EMBEDDING_MODEL,
    ) -> Any:
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("Store display name is required.")

        return self._call(
            self.client.file_search_stores.create,
            config={"display_name": display_name, "embedding_model": embedding_model},
        )

    def list_stores(self, page_size: int = 20) -> list[Any]:
        pager = self._call(
            self.client.file_search_stores.list,
            config={"page_size": page_size},
        )
        return list(pager)

    def get_store(self, name: str) -> Any:
        return self._call(self.client.file_search_stores.get, name=name)

    def delete_store(self, name: str, force: bool = True) -> None:
        self._call(
            self.client.file_search_stores.delete,
            name=name,
            config={"force": force},
        )

    def import_file(
        self,
        file_search_store_name: str,
        file_name: str,
        custom_metadata: list[dict[str, Any]] | None = None,
        wait: bool = True,
        poll_interval: float = 5.0,
        timeout_seconds: float = 600.0,
    ) -> Any:
        config: dict[str, Any] = {}
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        operation = self._call(
            self.client.file_search_stores.import_file,
            file_search_store_name=file_search_store_name,
            file_name=file_name,
            config=config or None,
        )
        if not wait:
            return operation
        return self.wait_for_operation(operation, poll_interval, timeout_seconds)

    def list_documents(self, parent: str, page_size: int = 20) -> list[Any]:
        pager = self._call(
            self.client.file_search_stores.documents.list,
            parent=parent,
            config={"page_size": page_size},
        )
        return list(pager)

    def get_document(self, name: str) -> Any:
        return self._call(self.client.file_search_stores.documents.get, name=name)

    def delete_document(self, name: str, force: bool = True) -> None:
        self._call(
            self.client.file_search_stores.documents.delete,
            name=name,
            config={"force": force},
        )

    def download_media(self, media_id: str) -> bytes:
        return self._call(self.client.file_search_stores.download_media, media_id=media_id)

    def wait_for_operation(
        self,
        operation: Any,
        poll_interval: float = 5.0,
        timeout_seconds: float = 600.0,
        progress_callback: Callable[[OperationStatus], None] | None = None,
    ) -> Any:
        deadline = time.monotonic() + timeout_seconds
        current = operation

        while not _get(current, "done"):
            if progress_callback:
                progress_callback(operation_status(current))
            if time.monotonic() >= deadline:
                raise OperationTimeoutError("File Search operation timed out before completion.")
            time.sleep(poll_interval)
            current = self._call(self.client.operations.get, current)

        status = operation_status(current)
        if progress_callback:
            progress_callback(status)
        if status.error:
            raise GeminiAPIError(format_api_error(to_plain_data(status.error), self.secrets))
        return current

    def _call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except GeminiAPIError:
            raise
        except Exception as exc:
            raise GeminiAPIError(format_api_error(exc, self.secrets)) from None


def operation_status(operation: Any) -> OperationStatus:
    return OperationStatus(
        name=_get(operation, "name"),
        done=bool(_get(operation, "done")),
        error=_get(operation, "error"),
        response=_get(operation, "response"),
        metadata=_get(operation, "metadata"),
    )


def object_name(value: Any) -> str | None:
    return _get(value, "name")


def object_display_name(value: Any) -> str | None:
    return _get(value, "display_name", "displayName")


def object_to_dict(value: Any) -> dict[str, Any]:
    data = to_plain_data(value)
    return data if isinstance(data, dict) else {"value": data}


def _get(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None
