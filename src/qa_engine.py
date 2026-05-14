from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from google.genai import types

from .citation_parser import GroundingResult, parse_grounding_metadata
from .config import format_api_error
from .file_search_manager import GeminiAPIError
from .validation import validate_model


ANSWER_SYSTEM_INSTRUCTION = (
    "Answer using only content retrieved from the selected Google Gemini File Search store. "
    "If the answer is not supported by retrieved store content, say that you do not know from "
    "the selected store. Do not use web search, URL context, Google Search grounding, or outside knowledge."
)


@dataclass(frozen=True)
class AnswerResult:
    text: str
    grounding: GroundingResult
    raw_response: Any


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

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=question,
                config=types.GenerateContentConfig(
                    system_instruction=ANSWER_SYSTEM_INSTRUCTION,
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
