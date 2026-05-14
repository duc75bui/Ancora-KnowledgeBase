from __future__ import annotations

from .config import format_api_error


class GeminiClientError(RuntimeError):
    pass


def create_client(api_key: str):
    if not api_key or not api_key.strip():
        raise GeminiClientError("A Gemini API key is required.")

    try:
        from google import genai

        return genai.Client(api_key=api_key.strip())
    except Exception as exc:  # pragma: no cover - depends on installed SDK internals
        raise GeminiClientError(format_api_error(exc, [api_key])) from None


def safe_api_error(exc: Exception, secrets: list[str | None] | tuple[str | None, ...] = ()) -> str:
    return format_api_error(exc, secrets)
