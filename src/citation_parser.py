from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Citation:
    title: str | None = None
    text: str | None = None
    uri: str | None = None
    file_search_store: str | None = None
    page_number: int | None = None
    media_id: str | None = None
    custom_metadata: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, [], {})}


@dataclass(frozen=True)
class GroundingResult:
    citations: list[Citation]
    grounding_supports: list[Any]
    raw_grounding_metadata: dict[str, Any] | None


def parse_grounding_metadata(response_or_metadata: Any) -> GroundingResult:
    metadata = _extract_grounding_metadata(response_or_metadata)
    raw = to_plain_data(metadata)
    chunks = _get(metadata, "grounding_chunks", "groundingChunks") or []
    supports = _get(metadata, "grounding_supports", "groundingSupports") or []

    citations: list[Citation] = []
    for chunk in chunks:
        retrieved_context = _get(chunk, "retrieved_context", "retrievedContext")
        if not retrieved_context:
            continue

        citations.append(
            Citation(
                title=_get(retrieved_context, "title"),
                text=_get(retrieved_context, "text"),
                uri=_get(retrieved_context, "uri"),
                file_search_store=_get(retrieved_context, "file_search_store", "fileSearchStore"),
                page_number=_get(retrieved_context, "page_number", "pageNumber"),
                media_id=_get(retrieved_context, "media_id", "mediaId"),
                custom_metadata=_normalize_custom_metadata(
                    _get(retrieved_context, "custom_metadata", "customMetadata")
                ),
            )
        )

    return GroundingResult(
        citations=citations,
        grounding_supports=to_plain_data(supports) or [],
        raw_grounding_metadata=raw,
    )


def to_plain_data(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {key: to_plain_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain_data(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            key: to_plain_data(item)
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    return value


def _extract_grounding_metadata(response_or_metadata: Any) -> Any:
    if response_or_metadata is None:
        return None

    direct = _get(response_or_metadata, "grounding_metadata", "groundingMetadata")
    if direct is not None:
        return direct

    candidates = _get(response_or_metadata, "candidates") or []
    if candidates:
        return _get(candidates[0], "grounding_metadata", "groundingMetadata")
    return response_or_metadata


def _normalize_custom_metadata(metadata: Any) -> list[dict[str, Any]] | None:
    if not metadata:
        return None
    normalized: list[dict[str, Any]] = []
    for item in metadata:
        data = to_plain_data(item)
        if isinstance(data, dict):
            normalized.append({key: value for key, value in data.items() if value is not None})
    return normalized or None


def _get(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None
