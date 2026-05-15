from __future__ import annotations

import html
from dataclasses import dataclass

from .citation_parser import Citation, GroundingResult


@dataclass(frozen=True)
class RenderedAnswer:
    html: str
    span_count: int


def render_answer_with_hover(
    answer_text: str,
    grounding: GroundingResult,
    media_data_urls: dict[str, str] | None = None,
) -> RenderedAnswer:
    media_data_urls = media_data_urls or {}
    spans = sorted(
        grounding.support_spans,
        key=lambda item: (item.start_index, item.end_index),
    )
    valid_spans = []
    last_end = 0
    for span in spans:
        if span.start_index < last_end:
            continue
        if span.start_index < 0 or span.end_index <= span.start_index:
            continue
        if span.end_index > len(answer_text):
            continue
        valid_spans.append(span)
        last_end = span.end_index

    parts: list[str] = [_style_block()]
    cursor = 0
    for span in valid_spans:
        parts.append(_format_text(answer_text[cursor : span.start_index]))
        span_text = answer_text[span.start_index : span.end_index]
        tooltip = _tooltip_html(span.citation_indices, grounding.citations, media_data_urls)
        label = _citation_label(span.citation_indices)
        parts.append(
            '<span class="citation-span" tabindex="0">'
            f"{_format_text(span_text)}"
            f'<sup class="citation-marker">{html.escape(label)}</sup>'
            f'<span class="citation-tooltip">{tooltip}</span>'
            "</span>"
        )
        cursor = span.end_index

    parts.append(_format_text(answer_text[cursor:]))
    if not valid_spans:
        parts.append('<p class="citation-note">No answer-span grounding supports were returned.</p>')
    return RenderedAnswer(html=f'<div class="answer-root">{"".join(parts)}</div>', span_count=len(valid_spans))


def estimate_answer_height(answer_text: str, span_count: int) -> int:
    line_count = max(3, answer_text.count("\n") + len(answer_text) // 95 + 1)
    return min(900, max(220, line_count * 32 + span_count * 10 + 120))


def _citation_label(indices: list[int]) -> str:
    if not indices:
        return "?"
    return ",".join(str(index + 1) for index in indices[:3])


def _tooltip_html(
    indices: list[int],
    citations: list[Citation],
    media_data_urls: dict[str, str],
) -> str:
    if not indices:
        return '<span class="tooltip-title">Grounding metadata</span><span>No citation index was returned.</span>'

    sections: list[str] = []
    for index in indices[:3]:
        if index < 0 or index >= len(citations):
            continue
        citation = citations[index]
        title = citation.title or citation.uri or citation.media_id or "Retrieved context"
        meta_bits = []
        if citation.page_number is not None:
            meta_bits.append(f"page {citation.page_number}")
        if citation.file_search_store:
            meta_bits.append(citation.file_search_store)
        snippet = _compact(citation.text or "")
        media_preview = ""
        if citation.media_id and citation.media_id in media_data_urls:
            media_preview = (
                '<img class="tooltip-media" '
                f'src="{html.escape(media_data_urls[citation.media_id], quote=True)}" '
                f'alt="{html.escape(title, quote=True)}">'
            )
        sections.append(
            '<span class="tooltip-section">'
            f'<span class="tooltip-title">{html.escape(title)}</span>'
            f'<span class="tooltip-meta">{html.escape(" | ".join(meta_bits))}</span>'
            f"{media_preview}"
            f'<span class="tooltip-snippet">{html.escape(snippet)}</span>'
            "</span>"
        )
    if not sections:
        return '<span class="tooltip-title">Grounding metadata</span><span>Citation details were not returned.</span>'
    return "".join(sections)


def _compact(text: str, limit: int = 520) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _format_text(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _style_block() -> str:
    return """
<style>
.answer-root {
  color: #17202a;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.65;
  padding: 4px 2px 24px;
}
.citation-span {
  position: relative;
  background: #fff4c2;
  border-bottom: 2px solid #c99700;
  cursor: help;
}
.citation-marker {
  color: #6f5300;
  font-size: 11px;
  font-weight: 700;
  margin-left: 2px;
}
.citation-tooltip {
  background: #111827;
  border: 1px solid #374151;
  border-radius: 8px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.28);
  color: #f9fafb;
  display: none;
  left: 0;
  min-width: 280px;
  max-width: min(520px, 90vw);
  padding: 12px;
  position: absolute;
  top: calc(100% + 8px);
  white-space: normal;
  z-index: 20;
}
.citation-span:hover .citation-tooltip,
.citation-span:focus .citation-tooltip {
  display: block;
}
.tooltip-section {
  display: block;
}
.tooltip-section + .tooltip-section {
  border-top: 1px solid #374151;
  margin-top: 10px;
  padding-top: 10px;
}
.tooltip-title {
  display: block;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 4px;
}
.tooltip-meta {
  color: #cbd5e1;
  display: block;
  font-size: 12px;
  margin-bottom: 6px;
}
.tooltip-snippet {
  display: block;
  font-size: 13px;
  line-height: 1.45;
}
.tooltip-media {
  border-radius: 6px;
  display: block;
  margin: 8px 0;
  max-height: 240px;
  max-width: 100%;
  object-fit: contain;
}
.citation-note {
  color: #64748b;
  font-size: 13px;
  margin-top: 12px;
}
</style>
"""
