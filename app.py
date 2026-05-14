from __future__ import annotations

import json
from typing import Any

import streamlit as st

from src.citation_parser import Citation, to_plain_data
from src.config import (
    DEFAULT_MODEL,
    FILE_SEARCH_EMBEDDING_MODEL,
    SUPPORTED_FILE_SEARCH_MODELS,
    load_config,
    mask_secret,
)
from src.file_search_manager import (
    FileSearchManager,
    GeminiAPIError,
    object_display_name,
    object_name,
    object_to_dict,
)
from src.gemini_client import GeminiClientError, create_client
from src.qa_engine import QAEngine
from src.upload_manager import UploadManager
from src.validation import accepted_extensions, safe_display_name, validate_file


st.set_page_config(page_title="Gemini File Search RAG", page_icon="G", layout="wide")


@st.cache_resource(show_spinner=False)
def cached_client(api_key: str):
    return create_client(api_key)


def main() -> None:
    st.title("Gemini File Search RAG")
    st.caption("Local Streamlit app using Google-managed File Search stores for retrieval.")

    config = load_config()
    api_key = render_api_key_controls(config.api_key)
    model = render_model_controls()

    if not api_key:
        st.info("Set GEMINI_API_KEY in .env or enter a Gemini API key in the sidebar to continue.")
        return

    try:
        client = cached_client(api_key)
    except GeminiClientError as exc:
        st.error(str(exc))
        return

    file_search = FileSearchManager(client, secrets=[api_key])
    upload_manager = UploadManager(client, secrets=[api_key])
    qa_engine = QAEngine(client, secrets=[api_key])

    stores = load_stores(file_search)
    selected_store_name = render_store_selector(stores)

    stores_tab, upload_tab, ask_tab, documents_tab = st.tabs(
        ["Stores", "Upload", "Ask", "Documents"]
    )
    with stores_tab:
        render_stores_tab(file_search, stores)
    with upload_tab:
        render_upload_tab(upload_manager, selected_store_name)
    with ask_tab:
        render_ask_tab(qa_engine, file_search, model, selected_store_name)
    with documents_tab:
        render_documents_tab(file_search, selected_store_name)


def render_api_key_controls(env_api_key: str | None) -> str | None:
    st.sidebar.header("Connection")
    if env_api_key:
        st.sidebar.success(f"Using GEMINI_API_KEY {mask_secret(env_api_key)}")
        return env_api_key

    entered = st.sidebar.text_input("Gemini API key", type="password")
    return entered.strip() if entered else None


def render_model_controls() -> str:
    model_ids = list(SUPPORTED_FILE_SEARCH_MODELS)
    default_index = model_ids.index(DEFAULT_MODEL) if DEFAULT_MODEL in model_ids else 0
    selected = st.sidebar.selectbox(
        "File Search model",
        options=model_ids,
        index=default_index,
        format_func=lambda model: f"{SUPPORTED_FILE_SEARCH_MODELS[model]} ({model})",
    )
    st.sidebar.caption("Model list follows the File Search supported models table.")
    return selected


def load_stores(file_search: FileSearchManager) -> list[Any]:
    if "stores" not in st.session_state:
        st.session_state.stores = []

    col_a, col_b = st.sidebar.columns([1, 1])
    refresh = col_a.button("Refresh stores", use_container_width=True)
    if refresh or not st.session_state.stores:
        try:
            st.session_state.stores = file_search.list_stores(page_size=20)
        except GeminiAPIError as exc:
            st.sidebar.error(str(exc))
    col_b.write("")
    return st.session_state.stores


def render_store_selector(stores: list[Any]) -> str | None:
    st.sidebar.header("Store")
    if not stores:
        st.sidebar.warning("No File Search stores loaded.")
        return None

    names = [object_name(store) for store in stores if object_name(store)]
    selected = st.sidebar.selectbox(
        "Selected File Search store",
        options=names,
        format_func=lambda name: _store_label(name, stores),
    )
    return selected


def render_stores_tab(file_search: FileSearchManager, stores: list[Any]) -> None:
    st.subheader("File Search stores")
    with st.form("create-store", clear_on_submit=True):
        display_name = st.text_input("New store display name", placeholder="Product docs")
        st.caption(f"New stores use {FILE_SEARCH_EMBEDDING_MODEL} so documents and PNG/JPEG images can be indexed.")
        submitted = st.form_submit_button("Create store")
        if submitted:
            try:
                store = file_search.create_store(display_name)
                st.success(f"Created {object_name(store)}")
                st.session_state.stores = file_search.list_stores(page_size=20)
            except (ValueError, GeminiAPIError) as exc:
                st.error(str(exc))

    st.divider()
    if stores:
        st.dataframe([object_to_dict(store) for store in stores], use_container_width=True)
    else:
        st.info("Create a store or refresh after creating one in Google AI Studio.")

    with st.expander("Delete a store"):
        store_names = [object_name(store) for store in stores if object_name(store)]
        if not store_names:
            st.caption("No stores available.")
            return
        target = st.selectbox("Store to delete", store_names, key="delete-store")
        force = st.checkbox("Force delete", value=True)
        confirm = st.text_input("Type DELETE to confirm", key="delete-store-confirm")
        if st.button("Delete store", type="primary", disabled=confirm != "DELETE"):
            try:
                file_search.delete_store(target, force=force)
                st.success(f"Deleted {target}")
                st.session_state.stores = file_search.list_stores(page_size=20)
            except GeminiAPIError as exc:
                st.error(str(exc))


def render_upload_tab(upload_manager: UploadManager, selected_store_name: str | None) -> None:
    st.subheader("Upload documents or images")
    if not selected_store_name:
        st.info("Select or create a File Search store first.")
        return

    uploaded_files = st.file_uploader(
        "Files",
        type=accepted_extensions(),
        accept_multiple_files=True,
        help="Google File Search handles import, chunking, embedding, indexing, and retrieval.",
    )
    wait_for_import = st.checkbox("Wait for import/indexing operation to finish", value=True)
    poll_interval = st.number_input("Poll interval seconds", min_value=1, max_value=30, value=5)

    if st.button("Upload to selected store", disabled=not uploaded_files):
        for uploaded_file in uploaded_files:
            data = uploaded_file.getvalue()
            validation = validate_file(
                uploaded_file.name,
                len(data),
                getattr(uploaded_file, "type", None),
                data=data,
            )
            if not validation.is_valid:
                st.error(f"{uploaded_file.name}: {'; '.join(validation.errors)}")
                continue
            for warning in validation.warnings:
                st.warning(f"{uploaded_file.name}: {warning}")

            with st.spinner(f"Uploading {uploaded_file.name}"):
                try:
                    result = upload_manager.upload_file_bytes(
                        file_search_store_name=selected_store_name,
                        filename=uploaded_file.name,
                        data=data,
                        content_type=validation.mime_type,
                        display_name=safe_display_name(uploaded_file.name),
                        wait=wait_for_import,
                        poll_interval=float(poll_interval),
                    )
                    st.success(f"Uploaded {uploaded_file.name} as {result.mime_type}")
                    st.json(to_plain_data(result.final_operation or result.operation))
                except (ValueError, GeminiAPIError) as exc:
                    st.error(f"{uploaded_file.name}: {exc}")


def render_ask_tab(
    qa_engine: QAEngine,
    file_search: FileSearchManager,
    model: str,
    selected_store_name: str | None,
) -> None:
    st.subheader("Ask the selected store")
    if not selected_store_name:
        st.info("Select or create a File Search store first.")
        return

    with st.form("ask-form"):
        question = st.text_area("Question", height=120)
        metadata_filter = st.text_input("Optional metadata filter", placeholder='author="Robert Graves"')
        top_k = st.number_input("Optional top_k", min_value=0, max_value=50, value=0)
        submitted = st.form_submit_button("Ask")

    if submitted:
        with st.spinner("Querying File Search"):
            try:
                result = qa_engine.answer(
                    question=question,
                    model=model,
                    file_search_store_name=selected_store_name,
                    metadata_filter=metadata_filter.strip() or None,
                    top_k=int(top_k) if top_k else None,
                )
            except (ValueError, GeminiAPIError) as exc:
                st.error(str(exc))
                return

        st.markdown("### Answer")
        st.markdown(result.text or "_No text returned._")
        render_citations(file_search, result.grounding.citations)
        with st.expander("Raw grounding metadata"):
            st.json(result.grounding.raw_grounding_metadata or {})
        with st.expander("Raw response"):
            st.json(to_plain_data(result.raw_response))


def render_citations(file_search: FileSearchManager, citations: list[Citation]) -> None:
    st.markdown("### Citations and grounding")
    if not citations:
        st.info("No grounding metadata citations were returned.")
        return

    st.dataframe([citation.to_dict() for citation in citations], use_container_width=True)
    for index, citation in enumerate(citations, start=1):
        with st.expander(f"Citation {index}: {citation.title or citation.uri or citation.media_id or 'retrieved context'}"):
            st.json(citation.to_dict())
            if citation.text:
                st.write(citation.text)
            if citation.media_id and st.button("Fetch cited media", key=f"media-{index}"):
                try:
                    media = file_search.download_media(citation.media_id)
                    st.image(media)
                    st.download_button(
                        "Download cited media",
                        data=media,
                        file_name=f"citation-{index}.bin",
                    )
                except GeminiAPIError as exc:
                    st.error(str(exc))


def render_documents_tab(file_search: FileSearchManager, selected_store_name: str | None) -> None:
    st.subheader("Documents in selected store")
    if not selected_store_name:
        st.info("Select or create a File Search store first.")
        return

    if st.button("List documents"):
        try:
            st.session_state.documents = file_search.list_documents(selected_store_name, page_size=20)
        except GeminiAPIError as exc:
            st.error(str(exc))

    documents = st.session_state.get("documents", [])
    if documents:
        st.dataframe([object_to_dict(document) for document in documents], use_container_width=True)
        with st.expander("Delete a document"):
            names = [object_name(document) for document in documents if object_name(document)]
            target = st.selectbox("Document to delete", names)
            force = st.checkbox("Force delete document chunks", value=True)
            if st.button("Delete document", type="primary"):
                try:
                    file_search.delete_document(target, force=force)
                    st.success(f"Deleted {target}")
                    st.session_state.documents = file_search.list_documents(selected_store_name, page_size=20)
                except GeminiAPIError as exc:
                    st.error(str(exc))
    else:
        st.caption("No documents loaded yet.")


def _store_label(name: str, stores: list[Any]) -> str:
    for store in stores:
        if object_name(store) == name:
            display_name = object_display_name(store)
            return f"{display_name} ({name})" if display_name else name
    return name


if __name__ == "__main__":
    main()
