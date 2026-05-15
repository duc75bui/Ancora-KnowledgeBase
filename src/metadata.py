from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


MAX_FILE_SEARCH_CUSTOM_METADATA_ITEMS = 20
RESERVED_METADATA_KEYS = {"source_id", "source_filename", "source_sha256"}
METADATA_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
NUMERIC_VALUE_PATTERN = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


@dataclass(frozen=True)
class MetadataBuildResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def build_common_metadata(fields: Mapping[str, str | None]) -> MetadataBuildResult:
    """Build validated File Search metadata from named text fields."""
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()

    for key, value in fields.items():
        normalized_value = (value or "").strip()
        if not normalized_value:
            continue
        error = validate_metadata_key(key)
        if error:
            errors.append(error)
            continue
        if key in seen:
            errors.append(f"Duplicate metadata key: {key}")
            continue
        seen.add(key)
        items.append({"key": key, "string_value": normalized_value})

    return MetadataBuildResult(items=items, errors=errors)


def build_metadata_from_editor_rows(rows: Any) -> MetadataBuildResult:
    """Build metadata from Streamlit data_editor rows."""
    records = _normalize_rows(rows)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()

    for index, row in enumerate(records, start=1):
        key = str(row.get("key", "") or "").strip()
        raw_value = str(row.get("value", "") or "").strip()
        value_type = str(row.get("type", "String") or "String").strip()
        if not key and not raw_value:
            continue
        if not key or not raw_value:
            errors.append(f"Metadata row {index} needs both key and value.")
            continue
        key_error = validate_metadata_key(key)
        if key_error:
            errors.append(f"Metadata row {index}: {key_error}")
            continue
        if key in seen:
            errors.append(f"Duplicate metadata key: {key}")
            continue
        seen.add(key)
        item, value_error = metadata_item_from_value(key, raw_value, value_type)
        if value_error:
            errors.append(f"Metadata row {index}: {value_error}")
            continue
        items.append(item)

    return MetadataBuildResult(items=items, errors=errors)


def parse_metadata_lines(raw_text: str) -> MetadataBuildResult:
    """Parse advanced metadata lines in key=value format."""
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()

    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f"Line {line_number}: use key=value format.")
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        key_error = validate_metadata_key(key)
        if key_error:
            errors.append(f"Line {line_number}: {key_error}")
            continue
        if key in seen:
            errors.append(f"Duplicate metadata key: {key}")
            continue
        seen.add(key)
        item, value_error = metadata_item_from_auto_value(key, raw_value)
        if value_error:
            errors.append(f"Line {line_number}: {value_error}")
            continue
        items.append(item)

    return MetadataBuildResult(items=items, errors=errors)


def merge_metadata(
    *groups: Iterable[dict[str, Any]],
    max_items: int = MAX_FILE_SEARCH_CUSTOM_METADATA_ITEMS,
) -> MetadataBuildResult:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for item in group:
            key = str(item.get("key", "") or "").strip()
            key_error = validate_metadata_key(key, allow_reserved=True)
            if key_error:
                errors.append(key_error)
                continue
            if key in seen:
                errors.append(f"Duplicate metadata key: {key}")
                continue
            seen.add(key)
            items.append(item)

    if len(items) > max_items:
        errors.append(
            f"File Search supports at most {max_items} custom metadata entries per document; "
            f"got {len(items)}."
        )

    return MetadataBuildResult(items=items, errors=errors)


def validate_metadata_key(key: str, allow_reserved: bool = False) -> str | None:
    if not key:
        return "Metadata key is required."
    if not METADATA_KEY_PATTERN.match(key):
        return (
            "Metadata key must start with a letter and contain only letters, "
            "numbers, and underscores."
        )
    if not allow_reserved and key in RESERVED_METADATA_KEYS:
        return f"`{key}` is reserved for the app's source archive metadata."
    return None


def metadata_item_from_value(
    key: str,
    raw_value: str,
    value_type: str = "String",
) -> tuple[dict[str, Any], str | None]:
    value = raw_value.strip()
    if not value:
        return {}, "Metadata value is required."

    if value_type == "Number":
        if not NUMERIC_VALUE_PATTERN.match(value):
            return {}, f"`{value}` is not a valid number."
        return {"key": key, "numeric_value": float(value)}, None

    return {"key": key, "string_value": value}, None


def metadata_item_from_auto_value(key: str, raw_value: str) -> tuple[dict[str, Any], str | None]:
    value = raw_value.strip()
    if not value:
        return {}, "Metadata value is required."

    if _is_quoted(value):
        return {"key": key, "string_value": value[1:-1]}, None

    list_values = _parse_string_list(value)
    if list_values is not None:
        if not list_values:
            return {}, "String list metadata must contain at least one value."
        return {"key": key, "string_list_value": {"values": list_values}}, None

    if NUMERIC_VALUE_PATTERN.match(value):
        return {"key": key, "numeric_value": float(value)}, None

    return {"key": key, "string_value": value}, None


def build_simple_metadata_filter(
    key: str | None,
    operator: str,
    value: str | None,
    value_type: str,
    advanced_filter: str | None = None,
) -> MetadataBuildResult:
    advanced = (advanced_filter or "").strip()
    if advanced:
        return MetadataBuildResult(items=[{"filter": advanced}])

    key = (key or "").strip()
    value = (value or "").strip()
    if not key and not value:
        return MetadataBuildResult()
    if not key or not value:
        return MetadataBuildResult(errors=["Metadata filter needs both key and value."])
    key_error = validate_metadata_key(key, allow_reserved=True)
    if key_error:
        return MetadataBuildResult(errors=[key_error])
    if operator not in {"=", "!=", "<", ">", "<=", ">="}:
        return MetadataBuildResult(errors=["Unsupported metadata filter operator."])
    if value_type == "Number":
        if not NUMERIC_VALUE_PATTERN.match(value):
            return MetadataBuildResult(errors=[f"`{value}` is not a valid number."])
        return MetadataBuildResult(items=[{"filter": f"{key} {operator} {value}"}])

    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return MetadataBuildResult(items=[{"filter": f'{key} {operator} "{escaped}"'}])


def metadata_filter_value(result: MetadataBuildResult) -> str | None:
    if result.errors or not result.items:
        return None
    value = result.items[0].get("filter")
    return str(value) if value else None


def _normalize_rows(rows: Any) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if hasattr(rows, "to_dict"):
        return rows.to_dict("records")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _is_quoted(value: str) -> bool:
    return len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}


def _parse_string_list(value: str) -> list[str] | None:
    if not (value.startswith("[") and value.endswith("]")):
        return None
    inner = value[1:-1].strip()
    if not inner:
        return []
    parsed: list[str] = []
    for item in inner.split(","):
        text = item.strip()
        if _is_quoted(text):
            text = text[1:-1]
        if text:
            parsed.append(text)
    return parsed
