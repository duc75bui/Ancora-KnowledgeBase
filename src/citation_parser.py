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
    support_spans: list["GroundingSupportSpan"]
    raw_grounding_metadata: dict[str, Any] | None


@dataclass(frozen=True)
class GroundingSupportSpan:
    start_index: int
    end_index: int
    text: str | None
    citation_indices: list[int]
    confidence_scores: list[float] | None = None


def parse_grounding_metadata(response_or_metadata: Any) -> GroundingResult:
    metadata = _extract_grounding_metadata(response_or_metadata)
    raw = to_plain_data(metadata)
    chunks = _get(metadata, "grounding_chunks", "groundingChunks") or []
    supports = _get(metadata, "grounding_supports", "groundingSupports") or []

    citations: list[Citation] = []
    chunk_to_citation_index: dict[int, int] = {}
    for chunk_index, chunk in enumerate(chunks):
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
        chunk_to_citation_index[chunk_index] = len(citations) - 1

    return GroundingResult(
        citations=citations,
        grounding_supports=to_plain_data(supports) or [],
        support_spans=_parse_support_spans(supports, chunk_to_citation_index),
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


def _parse_support_spans(
    supports: Any,
    chunk_to_citation_index: dict[int, int],
) -> list[GroundingSupportSpan]:
    spans: list[GroundingSupportSpan] = []
    for support in supports or []:
        segment = _get(support, "segment")
        start_index = _get(segment, "start_index", "startIndex")
        end_index = _get(segment, "end_index", "endIndex")
        if start_index is None or end_index is None:
            continue

        raw_indices = _get(support, "grounding_chunk_indices", "groundingChunkIndices") or []
        if not raw_indices:
            raw_index = _get(support, "grounding_chunk_index", "groundingChunkIndex")
            raw_indices = [raw_index] if raw_index is not None else []

        citation_indices = []
        for index in raw_indices:
            if index in chunk_to_citation_index:
                citation_indices.append(chunk_to_citation_index[index])

        spans.append(
            GroundingSupportSpan(
                start_index=int(start_index),
                end_index=int(end_index),
                text=_get(segment, "text"),
                citation_indices=citation_indices,
                confidence_scores=to_plain_data(
                    _get(support, "confidence_scores", "confidenceScores")
                ),
            )
        )
    return spans


def _get(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None
