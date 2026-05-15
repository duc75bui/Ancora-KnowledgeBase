from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from google.genai import types

from .citation_parser import GroundingResult, parse_grounding_metadata
from .config import format_api_error
from .file_search_manager import GeminiAPIError
from .validation import validate_model


ANSWER_SYSTEM_INSTRUCTION = (
    "Use attached user images only as question context. Ground factual answers in content retrieved "
    "from the selected Google Gemini File Search store. If a conclusion is based only on an attached "
    "user image and not on retrieved store content, say so clearly. If the answer is not supported by "
    "the uploaded image or retrieved store content, say that you do not know. Do not use web search, "
    "URL context, Google Search grounding, or outside knowledge."
)

WEB_ANSWER_SYSTEM_INSTRUCTION = (
    "Use Google Search grounding for this generic web question. Do not use a File Search store. "
    "Base factual claims on the returned web grounding metadata, and say when the web results do not "
    "support a confident answer."
)

ANSWER_STYLE_INSTRUCTIONS: dict[str, str] = {
    "Concise": (
        "Be concise. Answer in 2-5 focused sentences unless the user asks for more detail. "
        "Keep citations and caveats, but avoid long background."
    ),
    "Balanced": (
        "Use a balanced level of detail. Give the direct answer first, then include the most relevant "
        "supporting details from the sources."
    ),
    "Very deep technical": (
        "Provide a deep technical answer grounded in the sources. Include architecture, implementation "
        "details, edge cases, assumptions, limitations, and source-backed reasoning. Use headings or "
        "bullets when they improve clarity."
    ),
}
DEFAULT_ANSWER_STYLE = "Balanced"


@dataclass(frozen=True)
class AnswerResult:
    text: str
    grounding: GroundingResult
    raw_response: Any


@dataclass(frozen=True)
class QueryImage:
    filename: str
    data: bytes
    mime_type: str


class QAEngine:
    def __init__(self, client: Any, secrets: Iterable[str | None] = ()):
        self.client = client
        self.secrets = tuple(secrets)

    def answer(
        self,
        question: str,
        model: str,
        file_search_store_name: str,
        metadata_filter: str | None = None,
        top_k: int | None = None,
        query_images: list[QueryImage] | None = None,
        answer_style: str = DEFAULT_ANSWER_STYLE,
    ) -> AnswerResult:
        validate_model(model)
        question = question.strip()
        if not question:
            raise ValueError("Question is required.")
        if not file_search_store_name:
            raise ValueError("A File Search store is required.")

        file_search_config: dict[str, Any] = {
            "file_search_store_names": [file_search_store_name],
        }
        if metadata_filter:
            file_search_config["metadata_filter"] = metadata_filter
        if top_k:
            file_search_config["top_k"] = top_k

        query_images = query_images or []
        contents = build_contents(question, query_images)

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=build_system_instruction(
                        ANSWER_SYSTEM_INSTRUCTION,
                        answer_style,
                    ),
                    temperature=0.2,
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(**file_search_config),
                        )
                    ],
                ),
            )
            return AnswerResult(
                text=getattr(response, "text", "") or "",
                grounding=parse_grounding_metadata(response),
                raw_response=response,
            )
        except Exception as exc:
            raise GeminiAPIError(format_api_error(exc, self.secrets)) from None

    def answer_web(
        self,
        question: str,
        model: str,
        query_images: list[QueryImage] | None = None,
        answer_style: str = DEFAULT_ANSWER_STYLE,
    ) -> AnswerResult:
        validate_model(model)
        question = question.strip()
        if not question:
            raise ValueError("Question is required.")

        query_images = query_images or []
        contents = build_contents(question, query_images)

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=build_system_instruction(
                        WEB_ANSWER_SYSTEM_INSTRUCTION,
                        answer_style,
                    ),
                    temperature=0.2,
                    tools=[
                        types.Tool(
                            google_search=types.GoogleSearch(),
                        )
                    ],
                ),
            )
            return AnswerResult(
                text=getattr(response, "text", "") or "",
                grounding=parse_grounding_metadata(response),
                raw_response=response,
            )
        except Exception as exc:
            raise GeminiAPIError(format_api_error(exc, self.secrets)) from None


def build_contents(question: str, query_images: list[QueryImage]) -> str | list[Any]:
    if not query_images:
        return question
    image_parts = [
        types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
        for image in query_images
    ]
    return [
        *image_parts,
        question,
    ]


def build_system_instruction(base_instruction: str, answer_style: str) -> str:
    style_instruction = ANSWER_STYLE_INSTRUCTIONS.get(
        answer_style,
        ANSWER_STYLE_INSTRUCTIONS[DEFAULT_ANSWER_STYLE],
    )
    return f"{base_instruction}\n\nResponse style: {style_instruction}"
