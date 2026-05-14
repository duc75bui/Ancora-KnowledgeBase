import os

import pytest

from src.file_search_manager import FileSearchManager
from src.gemini_client import create_client


@pytest.mark.live
def test_live_smoke_lists_file_search_stores():
    if os.getenv("RUN_LIVE_GEMINI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_GEMINI_TESTS=1 to run the live Gemini File Search smoke test.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY is not set; live Gemini File Search smoke test skipped.")

    client = create_client(api_key)
    stores = FileSearchManager(client, secrets=[api_key]).list_stores(page_size=1)

    assert isinstance(stores, list)
