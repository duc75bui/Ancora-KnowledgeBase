from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_MODEL, SUPPORTED_FILE_SEARCH_MODELS, format_api_error


APP_CONFIG_DIR = Path(".app_config")
MODEL_CONFIG_PATH = APP_CONFIG_DIR / "models.json"


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    display_name: str
    source: str = "default"


class ModelManagerError(RuntimeError):
    pass


class ModelManager:
    def __init__(self, config_path: Path = MODEL_CONFIG_PATH):
        self.config_path = config_path

    def approved_models(self) -> dict[str, str]:
        approved = dict(SUPPORTED_FILE_SEARCH_MODELS)
        data = self._read_config()
        for model in data.get("approved_models", []):
            model_id = normalize_model_id(model.get("model_id"))
            display_name = model.get("display_name") or model_id
            if model_id:
                approved[model_id] = display_name
        return approved

    def discovered_models(self) -> list[ModelInfo]:
        data = self._read_config()
        return [
            ModelInfo(
                model_id=item["model_id"],
                display_name=item.get("display_name") or item["model_id"],
                source=item.get("source", "discovered"),
            )
            for item in data.get("discovered_models", [])
            if normalize_model_id(item.get("model_id"))
        ]

    def refresh_from_client(self, client: Any, secrets: Iterable[str | None] = ()) -> list[ModelInfo]:
        try:
            pager = client.models.list(config={"page_size": 100})
            models = list(pager)
        except Exception as exc:
            raise ModelManagerError(format_api_error(exc, secrets)) from None

        discovered: list[ModelInfo] = []
        seen: set[str] = set()
        for model in models:
            if not supports_generate_content(model):
                continue
            model_id = normalize_model_id(_get(model, "name"))
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            discovered.append(
                ModelInfo(
                    model_id=model_id,
                    display_name=_get(model, "display_name", "displayName") or model_id,
                    source="discovered",
                )
            )

        data = self._read_config()
        data["discovered_models"] = [asdict(item) for item in discovered]
        self._write_config(data)
        return discovered

    def approve_model(self, model_id: str, display_name: str | None = None) -> None:
        normalized = normalize_model_id(model_id)
        if not normalized:
            raise ValueError("Model ID must be a Gemini model name such as gemini-3-flash-preview.")

        data = self._read_config()
        approved = [
            item
            for item in data.get("approved_models", [])
            if normalize_model_id(item.get("model_id")) != normalized
        ]
        approved.append(
            {
                "model_id": normalized,
                "display_name": display_name or normalized,
                "source": "admin",
            }
        )
        data["approved_models"] = sorted(approved, key=lambda item: item["model_id"])
        self._write_config(data)

    def remove_approved_model(self, model_id: str) -> None:
        normalized = normalize_model_id(model_id)
        data = self._read_config()
        data["approved_models"] = [
            item
            for item in data.get("approved_models", [])
            if normalize_model_id(item.get("model_id")) != normalized
        ]
        self._write_config(data)

    def _read_config(self) -> dict[str, list[dict[str, str]]]:
        if not self.config_path.exists():
            return {"approved_models": [], "discovered_models": []}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"approved_models": [], "discovered_models": []}
        if not isinstance(data, dict):
            return {"approved_models": [], "discovered_models": []}
        for key in ("approved_models", "discovered_models"):
            if not isinstance(data.get(key), list):
                data[key] = []
        return data

    def _write_config(self, data: dict[str, list[dict[str, str]]]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.config_path)


def normalize_model_id(model_name: str | None) -> str | None:
    if not model_name:
        return None
    value = model_name.strip()
    if value.startswith("models/"):
        value = value.removeprefix("models/")
    if not value.startswith("gemini-"):
        return None
    if not all(character.isalnum() or character in ".-_" for character in value):
        return None
    return value


def supports_generate_content(model: Any) -> bool:
    actions = _get(model, "supported_actions", "supportedActions") or []
    return "generateContent" in actions


def default_model_from(approved_models: dict[str, str]) -> str:
    if DEFAULT_MODEL in approved_models:
        return DEFAULT_MODEL
    return next(iter(approved_models), DEFAULT_MODEL)


def _get(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None
