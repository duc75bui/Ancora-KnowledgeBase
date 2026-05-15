from src.answer_renderer import render_answer_with_hover
from src.citation_parser import Citation, GroundingResult, GroundingSupportSpan


def test_render_answer_wraps_supported_span_with_hover_citation():
    grounding = GroundingResult(
        citations=[
            Citation(
                title="policy.pdf",
                text='Approved <script>alert("x")</script> policy text',
                page_number=3,
                file_search_store="fileSearchStores/store-1",
            )
        ],
        grounding_supports=[],
        support_spans=[
            GroundingSupportSpan(
                start_index=0,
                end_index=17,
                text="Vacation is paid",
                citation_indices=[0],
            )
        ],
        raw_grounding_metadata=None,
    )

    rendered = render_answer_with_hover("Vacation is paid after approval.", grounding)

    assert rendered.span_count == 1
    assert "citation-span" in rendered.html
    assert "policy.pdf" in rendered.html
    assert "page 3" in rendered.html
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_render_answer_shows_note_when_no_spans():
    grounding = GroundingResult(
        citations=[],
        grounding_supports=[],
        support_spans=[],
        raw_grounding_metadata=None,
    )

    rendered = render_answer_with_hover("No span metadata.", grounding)

    assert rendered.span_count == 0
    assert "No answer-span grounding supports were returned." in rendered.html
