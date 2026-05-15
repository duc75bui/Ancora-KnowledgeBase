from __future__ import annotations

import base64
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from src.answer_renderer import estimate_answer_height, render_answer_with_hover
from src.auth import DEFAULT_ADMIN_PASSWORD, admin_password_from_env, verify_admin_password
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
from src.media_utils import data_url_for_displayable_image
from src.qa_engine import QAEngine
from src.source_registry import SourceRecord, SourceRegistry, source_id_from_custom_metadata
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
    is_admin = render_admin_controls()

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
    source_registry = SourceRegistry()

    stores = load_stores(file_search)
    selected_store_name = render_store_selector(stores)

    stores_tab, upload_tab, ask_tab, documents_tab = st.tabs(
        ["Stores", "Upload", "Ask", "Documents"]
    )
    with stores_tab:
        render_stores_tab(file_search, stores)
    with upload_tab:
        render_upload_tab(upload_manager, source_registry, selected_store_name)
    with ask_tab:
        render_ask_tab(qa_engine, file_search, source_registry, model, selected_store_name, is_admin)
    with documents_tab:
        render_documents_tab(file_search, source_registry, selected_store_name, is_admin)


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


def render_admin_controls() -> bool:
    st.sidebar.header("Admin")
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    if st.session_state.is_admin:
        st.sidebar.success("Admin access enabled")
        if st.sidebar.button("Log out admin"):
            st.session_state.is_admin = False
        return bool(st.session_state.is_admin)

    password = st.sidebar.text_input("Admin password", type="password")
    if admin_password_from_env() == DEFAULT_ADMIN_PASSWORD:
        st.sidebar.caption("Default test password is active. Set ADMIN_PASSWORD in .env before real use.")
    if st.sidebar.button("Log in as admin"):
        if verify_admin_password(password):
            st.session_state.is_admin = True
            st.sidebar.success("Admin access enabled")
        else:
            st.sidebar.error("Incorrect admin password")
    return bool(st.session_state.is_admin)


def load_stores(file_search: FileSearchManager) -> list[Any]:
    if "stores" not in st.session_state:
        st.session_state.stores = []

    col_a, col_b = st.sidebar.columns([1, 1])
    refresh = col_a.button("Refresh stores", width="stretch")
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
        st.dataframe([object_to_dict(store) for store in stores], width="stretch")
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


def render_upload_tab(
    upload_manager: UploadManager,
    source_registry: SourceRegistry,
    selected_store_name: str | None,
) -> None:
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
                source_record = None
                try:
                    source_record = source_registry.save_source(
                        filename=uploaded_file.name,
                        data=data,
                        mime_type=validation.mime_type or "application/octet-stream",
                        file_search_store_name=selected_store_name,
                    )
                    result = upload_manager.upload_file_bytes(
                        file_search_store_name=selected_store_name,
                        filename=uploaded_file.name,
                        data=data,
                        content_type=validation.mime_type,
                        display_name=safe_display_name(uploaded_file.name),
                        custom_metadata=source_record.to_file_search_metadata(),
                        wait=wait_for_import,
                        poll_interval=float(poll_interval),
                    )
                    st.success(f"Uploaded {uploaded_file.name} as {result.mime_type}")
                    st.caption(f"Local source archive id: {source_record.source_id}")
                    st.json(to_plain_data(result.final_operation or result.operation))
                except (ValueError, GeminiAPIError) as exc:
                    if source_record:
                        source_registry.delete_source(source_record.source_id)
                    st.error(f"{uploaded_file.name}: {exc}")


def render_ask_tab(
    qa_engine: QAEngine,
    file_search: FileSearchManager,
    source_registry: SourceRegistry,
    model: str,
    selected_store_name: str | None,
    is_admin: bool,
) -> None:
    st.subheader("Ask the selected store")
    if not selected_store_name:
        st.info("Select or create a File Search store first.")
        return

    with st.form("ask-form"):
        question = st.text_area("Question", height=120)
        metadata_filter = st.text_input("Optional metadata filter", placeholder='author="Robert Graves"')
        top_k = st.number_input("Optional top_k", min_value=0, max_value=50, value=0)
        include_media_previews = st.checkbox(
            "Show image citation previews in hover cards",
            value=True,
            help="When File Search returns media IDs, the app fetches cited media and embeds image thumbnails in hover cards.",
        )
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
        media_data_urls = {}
        source_image_data_urls = {}
        image_preview_notes = image_preview_notes_for_citations(
            result.grounding.citations,
            is_admin=is_admin,
        )
        if include_media_previews:
            media_data_urls, media_notes = citation_media_data_urls(
                file_search,
                result.grounding.citations,
            )
            image_preview_notes.update(media_notes)
            source_image_data_urls = citation_source_image_data_urls(
                source_registry,
                result.grounding.citations,
                file_search_store_name=selected_store_name,
                is_admin=is_admin,
            )
        if result.text:
            rendered = render_answer_with_hover(
                result.text,
                result.grounding,
                media_data_urls=media_data_urls,
                source_image_data_urls=source_image_data_urls,
                image_preview_notes=image_preview_notes,
            )
            components.html(
                rendered.html,
                height=estimate_answer_height(result.text, rendered.span_count),
                scrolling=True,
            )
        else:
            st.markdown("_No text returned._")
        render_citations(file_search, source_registry, result.grounding.citations, is_admin)
        with st.expander("Raw grounding metadata"):
            st.json(result.grounding.raw_grounding_metadata or {})
        with st.expander("Raw response"):
            st.json(to_plain_data(result.raw_response))


def render_citations(
    file_search: FileSearchManager,
    source_registry: SourceRegistry,
    citations: list[Citation],
    is_admin: bool,
) -> None:
    st.markdown("### Citations and grounding")
    if not citations:
        st.info("No grounding metadata citations were returned.")
        return

    st.dataframe([citation.to_dict() for citation in citations], width="stretch")
    for index, citation in enumerate(citations, start=1):
        with st.expander(f"Citation {index}: {citation.title or citation.uri or citation.media_id or 'retrieved context'}"):
            st.json(citation.to_dict())
            if citation.text:
                st.write(citation.text)
            render_citation_source_controls(
                source_registry=source_registry,
                citation=citation,
                is_admin=is_admin,
                key_prefix=f"citation-{index}",
            )
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


def render_documents_tab(
    file_search: FileSearchManager,
    source_registry: SourceRegistry,
    selected_store_name: str | None,
    is_admin: bool,
) -> None:
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
        st.dataframe([object_to_dict(document) for document in documents], width="stretch")
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

    render_source_archive(source_registry, selected_store_name, is_admin)


def render_citation_source_controls(
    source_registry: SourceRegistry,
    citation: Citation,
    is_admin: bool,
    key_prefix: str,
) -> None:
    source_id = source_id_from_custom_metadata(citation.custom_metadata)
    if not source_id:
        st.caption("No local source archive id was returned for this citation.")
        return
    if not is_admin:
        st.caption("Admin login required to view the original source file.")
        return

    record = source_registry.get(source_id)
    if record is None:
        st.warning("This citation references a local source id, but the archived file was not found.")
        return
    render_source_record_viewer(
        source_registry=source_registry,
        record=record,
        key_prefix=key_prefix,
        page_number=citation.page_number,
    )


def render_source_archive(
    source_registry: SourceRegistry,
    selected_store_name: str,
    is_admin: bool,
) -> None:
    st.divider()
    st.subheader("Local source archive")
    if not is_admin:
        st.info("Admin login is required to view or download locally archived source files.")
        return

    records = source_registry.list_records(selected_store_name)
    if not records:
        st.caption("No local originals have been archived for this store from this app.")
        return

    st.dataframe(
        [
            {
                "source_id": record.source_id,
                "filename": record.original_filename,
                "mime_type": record.mime_type,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "created_at": record.created_at,
            }
            for record in records
        ],
        width="stretch",
    )
    selected_id = st.selectbox(
        "Source file to view",
        [record.source_id for record in records],
        format_func=lambda source_id: _source_label(source_id, records),
    )
    record = source_registry.get(selected_id)
    if record:
        render_source_record_viewer(source_registry, record, key_prefix=f"archive-{record.source_id}")


def render_source_record_viewer(
    source_registry: SourceRegistry,
    record: SourceRecord,
    key_prefix: str,
    page_number: int | None = None,
) -> None:
    st.caption(f"Original source: {record.original_filename}")
    try:
        data = source_registry.file_bytes(record)
    except OSError as exc:
        st.error(f"Could not read archived source file: {exc}")
        return

    st.download_button(
        "Download original source",
        data=data,
        file_name=record.original_filename,
        mime=record.mime_type,
        key=f"{key_prefix}-download",
    )
    if record.mime_type == "application/pdf":
        show_pdf = st.checkbox("Show PDF preview", value=False, key=f"{key_prefix}-pdf-preview")
        if show_pdf:
            render_pdf_preview(data, page_number)
    elif record.mime_type in {"image/png", "image/jpeg"}:
        st.image(data, caption=record.original_filename)
    elif record.mime_type.startswith("text/") or record.mime_type in {"application/json", "application/xml"}:
        preview = data[:20_000].decode("utf-8", errors="replace")
        st.text_area("Source preview", value=preview, height=240, key=f"{key_prefix}-text-preview")


def render_pdf_preview(data: bytes, page_number: int | None = None) -> None:
    page_fragment = f"#page={page_number}" if page_number else ""
    encoded = base64.b64encode(data).decode("ascii")
    components.html(
        f"""
        <iframe
            src="data:application/pdf;base64,{encoded}{page_fragment}"
            width="100%"
            height="720"
            style="border: 1px solid #d0d7de; border-radius: 6px;"
            title="PDF source preview">
        </iframe>
        """,
        height=740,
        scrolling=False,
    )


def citation_media_data_urls(
    file_search: FileSearchManager,
    citations: list[Citation],
) -> tuple[dict[str, str], dict[str, str]]:
    media_data_urls: dict[str, str] = {}
    notes: dict[str, str] = {}
    for citation in citations:
        if not citation.media_id or citation.media_id in media_data_urls:
            continue
        try:
            media = file_search.download_media(citation.media_id)
        except GeminiAPIError as exc:
            notes[citation.media_id] = f"File Search returned a media ID, but the app could not download it: {exc}"
            continue
        data_url = data_url_for_displayable_image(media)
        if data_url:
            media_data_urls[citation.media_id] = data_url
        else:
            notes[citation.media_id] = "File Search returned media bytes, but they were not a browser-displayable image or were too large to inline."
    return media_data_urls, notes


def image_preview_notes_for_citations(
    citations: list[Citation],
    is_admin: bool,
) -> dict[str, str]:
    notes: dict[str, str] = {}
    for citation in citations:
        source_id = source_id_from_custom_metadata(citation.custom_metadata)
        if citation.media_id:
            notes.setdefault(citation.media_id, "File Search returned a media ID, but no image preview was prepared.")
            continue
        if source_id:
            if is_admin:
                notes.setdefault(source_id, "This citation maps to a local source file, but it is not an archived image preview.")
            else:
                notes.setdefault(source_id, "This citation has no File Search media ID. Log in as admin to view the locally archived source image if this upload came through the app.")
            continue
        title = (citation.title or "").lower()
        if title.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")):
            key = citation.title or title
            notes.setdefault(key, "File Search cited this image by name, but did not return a downloadable media ID.")
    return notes


def citation_source_image_data_urls(
    source_registry: SourceRegistry,
    citations: list[Citation],
    file_search_store_name: str,
    is_admin: bool,
) -> dict[str, str]:
    if not is_admin:
        return {}

    source_data_urls: dict[str, str] = {}
    for citation in citations:
        source_id = source_id_from_custom_metadata(citation.custom_metadata)
        record = source_registry.get(source_id) if source_id else None
        if record is None:
            record = source_registry.find_by_filename(
                citation.title,
                file_search_store_name=file_search_store_name,
            )
        if record is None or record.source_id in source_data_urls:
            continue
        if not record.mime_type.startswith("image/"):
            continue
        try:
            data = source_registry.file_bytes(record)
        except OSError as exc:
            st.warning(f"Could not read archived image source preview: {exc}")
            continue
        data_url = data_url_for_displayable_image(data, record.mime_type)
        if data_url:
            source_data_urls[record.source_id] = data_url
            if citation.title:
                source_data_urls[citation.title] = data_url
    return source_data_urls


def _store_label(name: str, stores: list[Any]) -> str:
    for store in stores:
        if object_name(store) == name:
            display_name = object_display_name(store)
            return f"{display_name} ({name})" if display_name else name
    return name


def _source_label(source_id: str, records: list[SourceRecord]) -> str:
    for record in records:
        if record.source_id == source_id:
            return f"{record.original_filename} ({source_id[:8]})"
    return source_id


if __name__ == "__main__":
    main()
