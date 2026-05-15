from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


FILE_SEARCH_EMBEDDING_MODEL = "models/gemini-embedding-2"
DEFAULT_MODEL = "gemini-3-flash-preview"
TEMP_UPLOAD_DIR = Path(".tmp_uploads")
APP_VERSION = "2.00"
APP_NAME = f"ancoraDocs KnowledgeBase v{APP_VERSION}"

SUPPORTED_FILE_SEARCH_MODELS: dict[str, str] = {
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
    "gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash-Lite Preview",
    "gemini-3-flash-preview": "Gemini 3 Flash Preview",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash-Lite",
}


@dataclass(frozen=True)
class AppConfig:
    api_key: str | None
    default_model: str = DEFAULT_MODEL
    upload_dir: Path = TEMP_UPLOAD_DIR


def load_config(dotenv_path: str | Path | None = None) -> AppConfig:
    """Load app config from .env and process environment."""
    load_dotenv(dotenv_path=dotenv_path, override=False)
    api_key = os.getenv("GEMINI_API_KEY")
    return AppConfig(api_key=api_key.strip() if api_key else None)


def mask_secret(secret: str | None) -> str:
    if not secret:
        return ""
    value = secret.strip()
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def sanitize_error(message: object, secrets: Iterable[str | None] = ()) -> str:
    """Remove full secrets from exception text before showing it in the UI."""
    text = str(message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, mask_secret(secret))

    text = re.sub(r"AIza[0-9A-Za-z_-]{16,}", "[masked API key]", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|key)=)([^&\s,;]+)",
        r"\1[masked]",
        text,
    )
    text = re.sub(
        r"(?i)((?:GEMINI_API_KEY|GOOGLE_API_KEY)\s*[:=]\s*)([^\s,;]+)",
        r"\1[masked]",
        text,
    )
    return text


def format_api_error(message: object, secrets: Iterable[str | None] = ()) -> str:
    """Return a user-facing API error with common Gemini key problems explained."""
    sanitized = sanitize_error(message, secrets)

    if _is_api_key_service_blocked(sanitized):
        return (
            "Google rejected this request because the API key's API restrictions block "
            "Gemini File Search on `generativelanguage.googleapis.com`.\n\n"
            "Fix the key in Google AI Studio or Google Cloud Console: use a Gemini API key "
            "with no API restriction for local testing, or restrict the key to the "
            "Generative Language API / Gemini API. Then refresh this app and try again.\n\n"
            f"Sanitized Google error: {sanitized}"
        )

    if "API_KEY_INVALID" in sanitized:
        return (
            "Google rejected this request because the Gemini API key is invalid. "
            "Create or copy a current Gemini API key from Google AI Studio, then try again.\n\n"
            f"Sanitized Google error: {sanitized}"
        )

    return sanitized


def _is_api_key_service_blocked(message: str) -> bool:
    return (
        "API_KEY_SERVICE_BLOCKED" in message
        or (
            "generativelanguage.googleapis.com" in message
            and "blocked" in message.lower()
            and "RetrieverService" in message
        )
    )
