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


def test_render_answer_can_embed_image_media_preview_in_hover():
    grounding = GroundingResult(
        citations=[
            Citation(
                title="diagram.png",
                text="The diagram shows the approval flow.",
                media_id="media-1",
            )
        ],
        grounding_supports=[],
        support_spans=[
            GroundingSupportSpan(
                start_index=0,
                end_index=11,
                text="The diagram",
                citation_indices=[0],
            )
        ],
        raw_grounding_metadata=None,
    )

    rendered = render_answer_with_hover(
        "The diagram explains the process.",
        grounding,
        media_data_urls={"media-1": "data:image/png;base64,abc123"},
    )

    assert "tooltip-media" in rendered.html
    assert "data:image/png;base64,abc123" in rendered.html
    assert "Exact cited image chunk" in rendered.html


def test_render_answer_can_embed_admin_source_image_preview_in_hover():
    grounding = GroundingResult(
        citations=[
            Citation(
                title="uploaded-image.png",
                text="The image shows the serial number.",
                custom_metadata=[{"key": "source_id", "string_value": "source-1"}],
            )
        ],
        grounding_supports=[],
        support_spans=[
            GroundingSupportSpan(
                start_index=0,
                end_index=9,
                text="The image",
                citation_indices=[0],
            )
        ],
        raw_grounding_metadata=None,
    )

    rendered = render_answer_with_hover(
        "The image shows the serial number.",
        grounding,
        source_image_data_urls={"source-1": "data:image/png;base64,sourcebytes"},
    )

    assert "tooltip-media" in rendered.html
    assert "Archived source image" in rendered.html
    assert "data:image/png;base64,sourcebytes" in rendered.html


def test_render_answer_explains_missing_image_preview():
    grounding = GroundingResult(
        citations=[Citation(title="diagram.png", text="The diagram shows the flow.")],
        grounding_supports=[],
        support_spans=[
            GroundingSupportSpan(
                start_index=0,
                end_index=11,
                text="The diagram",
                citation_indices=[0],
            )
        ],
        raw_grounding_metadata=None,
    )

    rendered = render_answer_with_hover("The diagram shows the flow.", grounding)

    assert "No image preview handle was returned for this citation." in rendered.html
    assert "diagram.png" in rendered.html
