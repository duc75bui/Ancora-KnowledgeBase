from src.config import format_api_error, load_config, mask_secret, sanitize_error


def test_load_config_reads_gemini_api_key(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=abc123456789\n", encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    config = load_config(env_file)

    assert config.api_key == "abc123456789"


def test_mask_secret_hides_middle():
    assert mask_secret("abcd1234wxyz") == "abcd...wxyz"
    assert mask_secret("short") == "*****"


def test_sanitize_error_replaces_known_secret_and_key_patterns():
    message = "request failed with key=abcd1234 and token AIzaSyDUMMYSECRETKEY123456789"

    sanitized = sanitize_error(message, ["abcd1234"])

    assert "abcd1234" not in sanitized
    assert "AIzaSyDUMMYSECRETKEY123456789" not in sanitized
    assert "[masked" in sanitized


def test_format_api_error_explains_service_blocked_key_restriction():
    raw = (
        "403 PERMISSION_DENIED. {'error': {'message': 'Requests to this API "
        "generativelanguage.googleapis.com method "
        "google.ai.generativelanguage.v1beta.RetrieverService.ListFileSearchStores "
        "are blocked.', 'details': [{'reason': 'API_KEY_SERVICE_BLOCKED'}]}}"
    )

    formatted = format_api_error(raw)

    assert "API key's API restrictions block Gemini File Search" in formatted
    assert "Generative Language API / Gemini API" in formatted
    assert "API_KEY_SERVICE_BLOCKED" in formatted
