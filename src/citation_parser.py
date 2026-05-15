from __future__ import annotations

from dataclasses import asdict, dataclass, replace
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
        web_context = _get(chunk, "web")
        if retrieved_context:
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
        elif web_context:
            citations.append(
                Citation(
                    title=_get(web_context, "title"),
                    uri=_get(web_context, "uri"),
                )
            )
        else:
            continue
        chunk_to_citation_index[chunk_index] = len(citations) - 1

    return GroundingResult(
        citations=citations,
        grounding_supports=to_plain_data(supports) or [],
        support_spans=_parse_support_spans(supports, chunk_to_citation_index),
        raw_grounding_metadata=raw,
    )


def supplement_missing_citation_details(
    primary: GroundingResult,
    fallback: GroundingResult | None,
    allow_index_fallback: bool = False,
) -> GroundingResult:
    """Fill missing citation details from an earlier grounding result."""
    if not fallback or not primary.citations or not fallback.citations:
        return primary

    citations: list[Citation] = []
    for index, citation in enumerate(primary.citations):
        fallback_citation = _matching_fallback_citation(
            index,
            citation,
            fallback.citations,
            allow_index_fallback=allow_index_fallback,
        )
        if fallback_citation is None:
            citations.append(citation)
            continue
        citations.append(
            replace(
                citation,
                text=citation.text or fallback_citation.text,
                uri=citation.uri or fallback_citation.uri,
                file_search_store=citation.file_search_store or fallback_citation.file_search_store,
                page_number=citation.page_number
                if citation.page_number is not None
                else fallback_citation.page_number,
                media_id=citation.media_id or fallback_citation.media_id,
                custom_metadata=citation.custom_metadata or fallback_citation.custom_metadata,
            )
        )

    return replace(primary, citations=citations)


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


def search_entry_point_html(response_or_metadata: Any) -> str | None:
    metadata = _extract_grounding_metadata(response_or_metadata)
    search_entry_point = _get(metadata, "search_entry_point", "searchEntryPoint")
    rendered_content = _get(search_entry_point, "rendered_content", "renderedContent")
    return rendered_content if isinstance(rendered_content, str) else None


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


def _matching_fallback_citation(
    index: int,
    citation: Citation,
    fallback_citations: list[Citation],
    allow_index_fallback: bool = False,
) -> Citation | None:
    if index < len(fallback_citations):
        fallback = fallback_citations[index]
        if _strong_citations_match(citation, fallback):
            return fallback
        if _same_title(citation, fallback) and _title_is_unique(citation.title, fallback_citations):
            return fallback
        if allow_index_fallback and _citation_needs_source_details(citation):
            return fallback

    strong_matches = [
        fallback
        for fallback in fallback_citations
        if _strong_citations_match(citation, fallback)
    ]
    if len(strong_matches) == 1:
        return strong_matches[0]

    if citation.title and _title_is_unique(citation.title, fallback_citations):
        for fallback in fallback_citations:
            if _same_title(citation, fallback):
                return fallback
    return None


def _strong_citations_match(left: Citation, right: Citation) -> bool:
    for field_name in ("media_id", "uri"):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value and right_value and left_value == right_value:
            return True
    return False


def _same_title(left: Citation, right: Citation) -> bool:
    return bool(left.title and right.title and left.title == right.title)


def _title_is_unique(title: str | None, citations: list[Citation]) -> bool:
    if not title:
        return False
    return sum(1 for citation in citations if citation.title == title) == 1


def _citation_needs_source_details(citation: Citation) -> bool:
    return (
        citation.page_number is None
        or not citation.media_id
        or not citation.custom_metadata
    )


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
