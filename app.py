from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

from src.answer_renderer import estimate_answer_height, render_answer_with_hover
from src.auth import DEFAULT_ADMIN_PASSWORD, admin_password_from_env, verify_admin_password
from src.citation_parser import (
    Citation,
    search_entry_point_html,
    supplement_missing_citation_details,
    to_plain_data,
)
from src.config import (
    APP_NAME,
    DEFAULT_MODEL,
    FILE_SEARCH_EMBEDDING_MODEL,
    SUPPORTED_FILE_SEARCH_MODELS,
    clear_persisted_api_key,
    load_config,
    mask_secret,
    save_persisted_api_key,
)
from src.file_search_manager import (
    FileSearchManager,
    GeminiAPIError,
    object_display_name,
    object_name,
    object_to_dict,
)
from src.gemini_client import GeminiClientError, create_client
from src.media_utils import data_url_for_displayable_image, validate_query_image
from src.metadata import (
    build_common_metadata,
    build_metadata_from_editor_rows,
    build_simple_metadata_filter,
    merge_metadata,
    metadata_filter_value,
    parse_metadata_lines,
)
from src.model_manager import ModelInfo, ModelManager, ModelManagerError, default_model_from
from src.qa_engine import ANSWER_STYLE_INSTRUCTIONS, DEFAULT_ANSWER_STYLE, QAEngine, QueryImage
from src.source_registry import SourceRecord, SourceRegistry, source_id_from_custom_metadata
from src.upload_manager import UploadManager
from src.validation import accepted_extensions, safe_display_name, validate_file


st.set_page_config(page_title=APP_NAME, page_icon="G", layout="wide")


@st.cache_resource(show_spinner=False)
def cached_client(api_key: str):
    return create_client(api_key)


def main() -> None:
    st.title(APP_NAME)
    st.caption("Local Streamlit app using Google-managed File Search stores for retrieval.")

    config = load_config()
    is_admin = current_admin_status()
    api_key = render_api_key_controls(
        config.api_key,
        api_key_source=config.api_key_source,
        is_admin=is_admin,
    )
    model_manager = ModelManager()
    approved_models = model_manager.approved_models()
    model = render_model_controls(approved_models)

    if not api_key:
        st.subheader("Ask")
        st.info(
            "A shared Gemini API key is not configured yet. Ask an admin to log in and "
            "save the key once; after that, users can ask without admin login."
        )
        render_admin_controls()
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
    selected_store_name = render_store_selector(stores, is_admin=is_admin)
    render_selected_source_viewer(source_registry, selected_store_name, is_admin)

    render_ask_tab(
        qa_engine,
        file_search,
        source_registry,
        model,
        selected_store_name,
        is_admin,
    )

    if is_admin:
        render_admin_panel(
            file_search=file_search,
            upload_manager=upload_manager,
            source_registry=source_registry,
            model_manager=model_manager,
            approved_models=approved_models,
            stores=stores,
            selected_store_name=selected_store_name,
            api_key=api_key,
        )
    render_admin_controls()


def render_api_key_controls(
    loaded_api_key: str | None,
    api_key_source: str | None,
    is_admin: bool,
) -> str | None:
    st.sidebar.header("Connection")
    if "session_api_key" not in st.session_state:
        st.session_state.session_api_key = None

    if loaded_api_key:
        st.session_state.session_api_key = loaded_api_key
        st.sidebar.text_input("Gemini API key", value=mask_secret(loaded_api_key), disabled=True)
        if api_key_source == "local":
            st.sidebar.success("Connected with saved local API key")
        else:
            st.sidebar.success("Connected with GEMINI_API_KEY from `.env` or the environment")
        if is_admin:
            if api_key_source == "local":
                st.sidebar.caption("This key is saved on this server in `.app_config/secrets.json`.")
                if st.sidebar.button("Change saved API key"):
                    clear_persisted_api_key()
                    st.session_state.session_api_key = None
                    cached_client.clear()
                    st.rerun()
            else:
                st.sidebar.caption("To rotate this key, update `.env` or the server environment.")
        return loaded_api_key

    session_api_key = st.session_state.get("session_api_key")
    if session_api_key:
        st.sidebar.text_input("Gemini API key", value=mask_secret(session_api_key), disabled=True)
        st.sidebar.success("Connected for this browser session")
        if is_admin:
            if st.sidebar.button("Save key on this server"):
                try:
                    save_persisted_api_key(session_api_key)
                except ValueError as exc:
                    st.sidebar.error(str(exc))
                    return session_api_key
                cached_client.clear()
                st.rerun()
            if st.sidebar.button("Change API key"):
                st.session_state.session_api_key = None
                cached_client.clear()
                st.rerun()
        return session_api_key

    if not is_admin:
        st.sidebar.warning("No shared API key is configured.")
        st.sidebar.caption("Admin login is required once to save the Gemini API key for all users.")
        return None

    entered = st.sidebar.text_input("Gemini API key", type="password")
    save_key = st.sidebar.checkbox("Save API key on this server", value=True)
    if st.sidebar.button("Connect API key", disabled=not entered):
        if save_key:
            try:
                save_persisted_api_key(entered)
            except ValueError as exc:
                st.sidebar.error(str(exc))
                return None
        st.session_state.session_api_key = entered.strip()
        cached_client.clear()
        st.rerun()
    return None


def render_model_controls(approved_models: dict[str, str]) -> str:
    model_ids = list(approved_models)
    default_model = default_model_from(approved_models)
    default_index = model_ids.index(default_model) if default_model in model_ids else 0
    selected = st.sidebar.selectbox(
        "File Search model",
        options=model_ids,
        index=default_index,
        format_func=lambda model: f"{approved_models[model]} ({model})",
    )
    st.sidebar.caption("Admins can refresh and approve additional Gemini models.")
    return selected


def current_admin_status() -> bool:
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False
    return bool(st.session_state.is_admin)


def render_admin_controls() -> bool:
    st.sidebar.header("Admin")
    current_admin_status()

    if st.session_state.is_admin:
        st.sidebar.success("Admin access enabled")
        if st.sidebar.button("Log out admin"):
            st.session_state.is_admin = False
            st.rerun()
        return bool(st.session_state.is_admin)

    password = st.sidebar.text_input("Admin password", type="password")
    if admin_password_from_env() == DEFAULT_ADMIN_PASSWORD:
        st.sidebar.caption("Default test password is active. Set ADMIN_PASSWORD in .env before real use.")
    if st.sidebar.button("Log in as admin"):
        if verify_admin_password(password):
            st.session_state.is_admin = True
            st.sidebar.success("Admin access enabled")
            st.rerun()
        else:
            st.sidebar.error("Incorrect admin password")
    return bool(st.session_state.is_admin)


def load_stores(file_search: FileSearchManager) -> list[Any]:
    if "stores" not in st.session_state:
        st.session_state.stores = []

    refresh = st.session_state.is_admin and st.sidebar.button("Refresh stores", width="stretch")
    if refresh or not st.session_state.stores:
        try:
            st.session_state.stores = file_search.list_stores(page_size=20)
        except GeminiAPIError as exc:
            st.sidebar.error(str(exc))
    return st.session_state.stores


def render_store_selector(stores: list[Any], is_admin: bool) -> str | None:
    st.sidebar.header("Store")
    if not stores:
        st.sidebar.warning("No File Search stores loaded.")
        st.info("No knowledge base store is available yet. Ask an admin to create a File Search store.")
        return None

    names = [object_name(store) for store in stores if object_name(store)]
    selected = st.sidebar.selectbox(
        "Selected File Search store",
        options=names,
        key="selected_store_name",
        format_func=lambda name: _store_label(name, stores),
    )
    return selected


def render_admin_panel(
    file_search: FileSearchManager,
    upload_manager: UploadManager,
    source_registry: SourceRegistry,
    model_manager: ModelManager,
    approved_models: dict[str, str],
    stores: list[Any],
    selected_store_name: str | None,
    api_key: str,
) -> None:
    st.divider()
    st.subheader("Admin")
    stores_tab, upload_tab, documents_tab, models_tab = st.tabs(
        ["Stores", "Upload", "Documents", "Models"]
    )
    with stores_tab:
        render_stores_tab(file_search, stores)
    with upload_tab:
        render_upload_tab(upload_manager, source_registry, selected_store_name)
    with documents_tab:
        render_documents_tab(file_search, source_registry, selected_store_name, is_admin=True)
    with models_tab:
        render_models_tab(model_manager, approved_models, file_search.client, api_key)


def render_models_tab(
    model_manager: ModelManager,
    approved_models: dict[str, str],
    client: Any,
    api_key: str,
) -> None:
    st.subheader("Approved models")
    st.caption(
        "Defaults follow the File Search docs. Refreshed models are candidates; approve only after confirming they work for this app."
    )
    st.dataframe(
        [
            {"model_id": model_id, "display_name": display_name}
            for model_id, display_name in approved_models.items()
        ],
        width="stretch",
    )

    custom_model = st.text_input("Approve model ID manually", placeholder="gemini-...")
    custom_display_name = st.text_input("Display name", placeholder="Gemini ...")
    if st.button("Approve manual model", disabled=not custom_model):
        try:
            model_manager.approve_model(custom_model, custom_display_name or custom_model)
            st.success(f"Approved {custom_model}")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    removable = [
        model_id
        for model_id in approved_models
        if model_id not in SUPPORTED_FILE_SEARCH_MODELS
    ]
    if removable:
        target = st.selectbox("Remove admin-approved model", removable)
        if st.button("Remove approved model"):
            model_manager.remove_approved_model(target)
            st.success(f"Removed {target}")
            st.rerun()

    st.divider()
    if st.button("Refresh available Gemini models"):
        try:
            discovered = model_manager.refresh_from_client(client, secrets=[api_key])
            st.success(f"Discovered {len(discovered)} generateContent-capable model(s).")
        except ModelManagerError as exc:
            st.error(str(exc))

    discovered = model_manager.discovered_models()
    if not discovered:
        st.caption("No refreshed model list is stored yet.")
        return

    st.dataframe(
        [
            {
                "model_id": model.model_id,
                "display_name": model.display_name,
                "approved": model.model_id in approved_models,
            }
            for model in discovered
        ],
        width="stretch",
    )
    candidates = [model for model in discovered if model.model_id not in approved_models]
    if candidates:
        selected = st.selectbox(
            "Approve discovered model",
            candidates,
            format_func=lambda model: f"{model.display_name} ({model.model_id})",
        )
        if st.button("Approve discovered model"):
            model_manager.approve_model(selected.model_id, selected.display_name)
            st.success(f"Approved {selected.model_id}")
            st.rerun()


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
    upload_metadata, metadata_errors = render_upload_metadata_controls()
    if metadata_errors:
        for error in metadata_errors:
            st.error(error)

    if st.button("Upload to selected store", disabled=not uploaded_files or bool(metadata_errors)):
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
                        custom_metadata=upload_metadata,
                    )
                    file_metadata = source_record.to_file_search_metadata()
                    metadata_result = merge_metadata(file_metadata)
                    if metadata_result.errors:
                        raise ValueError("; ".join(metadata_result.errors))
                    result = upload_manager.upload_file_bytes(
                        file_search_store_name=selected_store_name,
                        filename=uploaded_file.name,
                        data=data,
                        content_type=validation.mime_type,
                        display_name=safe_display_name(uploaded_file.name),
                        custom_metadata=metadata_result.items,
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


def render_upload_metadata_controls() -> tuple[list[dict[str, Any]], list[str]]:
    with st.expander("File Search metadata", expanded=False):
        st.caption(
            "Custom metadata is stored with each File Search document and can be used later "
            "with metadata filters. Google allows up to 20 metadata entries per document; "
            "this app reserves 3 for source archive linking."
        )
        col1, col2 = st.columns(2)
        with col1:
            document_title = st.text_input("Document title metadata", key="metadata_document_title")
            document_type = st.text_input("Document type", placeholder="policy, manual, diagram", key="metadata_document_type")
            department = st.text_input("Department", placeholder="Operations", key="metadata_department")
        with col2:
            project = st.text_input("Project", placeholder="ancoraDocs", key="metadata_project")
            owner = st.text_input("Owner/author", placeholder="Team or person", key="metadata_owner")
            version = st.text_input("Version", placeholder="1.0", key="metadata_version")

        source_url = st.text_input("Source URL or reference", key="metadata_source_url")
        rows = st.data_editor(
            [{"key": "", "value": "", "type": "String"}],
            key="metadata_editor_rows",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "key": st.column_config.TextColumn("Key"),
                "value": st.column_config.TextColumn("Value"),
                "type": st.column_config.SelectboxColumn("Type", options=["String", "Number"]),
            },
        )
        advanced_lines = st.text_area(
            "Advanced metadata lines",
            placeholder='author="Robert Graves"\nyear=1934\ntags=[policy, onboarding]',
            help="Use key=value, one item per line. Quote values that should stay strings.",
        )

        common = build_common_metadata(
            {
                "document_title": document_title,
                "document_type": document_type,
                "department": department,
                "project": project,
                "owner": owner,
                "version": version,
                "source_url": source_url,
            }
        )
        editor = build_metadata_from_editor_rows(rows)
        advanced = parse_metadata_lines(advanced_lines)
        merged = merge_metadata(common.items, editor.items, advanced.items, max_items=17)
        errors = [*common.errors, *editor.errors, *advanced.errors, *merged.errors]

        if merged.items:
            st.caption("Metadata to attach to each uploaded file:")
            st.dataframe(merged.items, width="stretch")
        else:
            st.caption("No additional metadata will be attached beyond the app's source archive metadata.")
        return merged.items, errors


def render_ask_tab(
    qa_engine: QAEngine,
    file_search: FileSearchManager,
    source_registry: SourceRegistry,
    model: str,
    selected_store_name: str | None,
    is_admin: bool,
) -> None:
    st.subheader("Ask")

    with st.form("ask-form"):
        question = st.text_area("Question", height=120)
        query_image_files = st.file_uploader(
            "Optional image context",
            type=["png", "jpg", "jpeg", "webp", "heic", "heif"],
            accept_multiple_files=True,
            help="Gemini image input supports PNG, JPEG, WebP, HEIC, and HEIF. These images are prompt context, not File Search store documents.",
        )
        answer_style = st.selectbox(
            "Answer depth",
            options=list(ANSWER_STYLE_INSTRUCTIONS),
            index=list(ANSWER_STYLE_INSTRUCTIONS).index(DEFAULT_ANSWER_STYLE),
            help="Controls how concise or technically deep the answer should be while staying grounded in the selected source mode.",
        )
        use_web = st.checkbox(
            "Get answers from web for generic questions",
            value=False,
            help="Uses Google Search grounding instead of the selected File Search store. Use this only for generic or current web questions, not knowledge-base questions.",
        )
        filter_key, filter_operator, filter_value, filter_value_type, advanced_metadata_filter = (
            render_metadata_filter_controls()
        )
        top_k = st.number_input(
            "Optional top_k",
            min_value=0,
            max_value=50,
            value=0,
            help="Limits how many File Search chunks Google can retrieve before answering. Leave 0 for Google's default behavior.",
        )
        reverify_answer = st.checkbox(
            "Review answer with a second File Search pass",
            value=True,
            help="Runs an extra File Search-grounded review call that checks the initial answer against the same selected store and corrects unsupported points.",
        )
        include_media_previews = st.checkbox(
            "Show image citation previews in hover cards",
            value=True,
            help="When File Search returns media IDs, the app fetches cited media and embeds image thumbnails in hover cards.",
        )
        submitted = st.form_submit_button("Ask")

    if submitted:
        query_images = build_query_images(query_image_files or [])
        if query_images is None:
            return

        if not use_web and not selected_store_name:
            st.error("Select or create a File Search store, or enable web answers for a generic web question.")
            return
        metadata_filter = None
        if not use_web:
            filter_result = build_simple_metadata_filter(
                filter_key,
                filter_operator,
                filter_value,
                filter_value_type,
                advanced_metadata_filter,
            )
            if filter_result.errors:
                st.error("; ".join(filter_result.errors))
                return
            metadata_filter = metadata_filter_value(filter_result)

        with st.spinner("Querying File Search"):
            try:
                if use_web:
                    result = qa_engine.answer_web(
                        question=question,
                        model=model,
                        query_images=query_images,
                        answer_style=answer_style,
                    )
                else:
                    result = qa_engine.answer(
                        question=question,
                        model=model,
                        file_search_store_name=selected_store_name or "",
                        metadata_filter=metadata_filter,
                        top_k=int(top_k) if top_k else None,
                        query_images=query_images,
                        answer_style=answer_style,
                    )
            except (ValueError, GeminiAPIError) as exc:
                st.error(str(exc))
                return

        initial_result = None
        if reverify_answer and not use_web:
            initial_result = result
            with st.spinner("Reviewing answer against the selected File Search store"):
                try:
                    result = qa_engine.reverify_answer(
                        question=question,
                        draft_answer=initial_result.text,
                        model=model,
                        file_search_store_name=selected_store_name or "",
                        metadata_filter=metadata_filter,
                        top_k=int(top_k) if top_k else None,
                        query_images=query_images,
                        answer_style=answer_style,
                    )
                    result = type(result)(
                        text=result.text,
                        grounding=supplement_missing_citation_details(
                            result.grounding,
                            initial_result.grounding,
                        ),
                        raw_response=result.raw_response,
                    )
                except (ValueError, GeminiAPIError) as exc:
                    st.warning(f"Review pass failed; showing the initial answer. {exc}")
                    result = initial_result

        st.markdown("### Answer")
        st.caption("Source mode: Google Search grounding" if use_web else "Source mode: selected File Search store")
        if metadata_filter:
            st.caption(f"Metadata filter: `{metadata_filter}`")
        if initial_result:
            st.caption("Review pass: second File Search reanalysis was enabled.")
        if query_images:
            st.caption(f"Used {len(query_images)} uploaded image(s) as question context.")
        media_data_urls = {}
        source_image_data_urls = {}
        source_view_links = citation_source_view_links(
            source_registry,
            result.grounding.citations,
            file_search_store_name=selected_store_name,
        )
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
                source_view_links=source_view_links,
            )
            components.html(
                rendered.html,
                height=estimate_answer_height(result.text, rendered.span_count),
                scrolling=True,
            )
        else:
            st.markdown("_No text returned._")
        render_citation_pdf_open_buttons(
            source_registry,
            result.grounding.citations,
            file_search_store_name=selected_store_name,
        )
        if initial_result:
            with st.expander("Initial answer before review"):
                st.markdown(initial_result.text or "_No text returned._")
                st.json(initial_result.grounding.raw_grounding_metadata or {})
        render_citations(file_search, source_registry, result.grounding.citations, is_admin)
        render_search_entry_point(result.raw_response)
        with st.expander("Raw grounding metadata"):
            st.json(result.grounding.raw_grounding_metadata or {})
        with st.expander("Raw response"):
            st.json(to_plain_data(result.raw_response))


def render_metadata_filter_controls() -> tuple[str, str, str, str, str]:
    with st.expander("File Search metadata filter", expanded=False):
        st.caption(
            "Use this to narrow retrieval to documents uploaded with matching metadata. "
            "The advanced box accepts Google's metadata_filter syntax."
        )
        col1, col2 = st.columns([2, 1])
        with col1:
            filter_key = st.text_input("Filter key", placeholder="department")
            filter_value = st.text_input("Filter value", placeholder="Operations")
        with col2:
            filter_operator = st.selectbox("Operator", ["=", "!=", "<", ">", "<=", ">="])
            filter_value_type = st.selectbox("Value type", ["String", "Number"])
        advanced_metadata_filter = st.text_input(
            "Advanced metadata_filter",
            placeholder='author = "Robert Graves"',
            help="If this is filled in, it overrides the simple key/value builder.",
        )
    return (
        filter_key,
        filter_operator,
        filter_value,
        filter_value_type,
        advanced_metadata_filter,
    )


def build_query_images(uploaded_files: list[Any]) -> list[QueryImage] | None:
    query_images: list[QueryImage] = []
    total_bytes = 0
    for uploaded_file in uploaded_files:
        data = uploaded_file.getvalue()
        validation = validate_query_image(
            filename=uploaded_file.name,
            data=data,
            content_type=getattr(uploaded_file, "type", None),
        )
        if not validation.is_valid:
            st.error(f"{uploaded_file.name}: {'; '.join(validation.errors)}")
            return None
        total_bytes += validation.size_bytes
        if total_bytes > 18 * 1024 * 1024:
            st.error("Combined inline query images must be under 18 MB.")
            return None
        query_images.append(
            QueryImage(
                filename=validation.filename,
                data=data,
                mime_type=validation.mime_type or "application/octet-stream",
            )
        )
    return query_images


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
            if citation.uri:
                st.markdown(f"[Open source]({citation.uri})")
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


def render_citation_pdf_open_buttons(
    source_registry: SourceRegistry,
    citations: list[Citation],
    file_search_store_name: str | None,
) -> None:
    targets = citation_source_view_targets(
        source_registry,
        citations,
        file_search_store_name,
    )
    if not targets:
        return

    st.markdown("#### Source PDF")
    for target in targets:
        page_number = target.get("page_number")
        title = target.get("title") or "PDF source"
        label = f"Open citation {target['citation_index']} PDF"
        if page_number:
            label = f"{label} at page {page_number}"
        if st.button(label, key=f"open-source-{target['citation_index']}-{target['source_id']}"):
            st.query_params["source_id"] = str(target["source_id"])
            if page_number:
                st.query_params["page"] = str(page_number)
            elif "page" in st.query_params:
                del st.query_params["page"]
            st.rerun()
        st.caption(title)


def render_search_entry_point(raw_response: Any) -> None:
    rendered_content = search_entry_point_html(raw_response)
    if not rendered_content:
        return
    with st.expander("Google Search suggestions"):
        components.html(rendered_content, height=120, scrolling=True)


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


def render_selected_source_viewer(
    source_registry: SourceRegistry,
    selected_store_name: str | None,
    is_admin: bool,
) -> None:
    source_id = _query_param_value(st.query_params.get("source_id"))
    if not source_id:
        return

    page_number = _positive_int(_query_param_value(st.query_params.get("page")))
    st.subheader("Cited source")
    if st.button("Close cited source viewer"):
        st.query_params.clear()
        st.rerun()

    if not is_admin:
        st.info("Admin login is required to view locally archived source files.")
        return

    record = source_registry.get(source_id)
    if record is None:
        st.warning("The cited source file is not available in the local archive.")
        return
    if selected_store_name and record.file_search_store_name != selected_store_name:
        st.warning("This local source belongs to a different File Search store.")
        return

    render_source_record_viewer(
        source_registry=source_registry,
        record=record,
        key_prefix=f"linked-source-{record.source_id}",
        page_number=page_number,
        force_pdf_preview=True,
    )
    st.divider()


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
                "custom_metadata": record.custom_metadata or [],
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
    force_pdf_preview: bool = False,
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
        show_pdf = st.checkbox(
            "Show PDF preview",
            value=force_pdf_preview,
            key=f"{key_prefix}-pdf-preview",
        )
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


def citation_source_view_links(
    source_registry: SourceRegistry,
    citations: list[Citation],
    file_search_store_name: str | None,
) -> dict[str, str]:
    links: dict[str, str] = {}
    for citation in citations:
        record = _citation_source_record(
            source_registry,
            citation,
            file_search_store_name,
        )
        if record is None or record.mime_type != "application/pdf":
            continue
        params = {"source_id": record.source_id}
        if citation.page_number:
            params["page"] = str(citation.page_number)
        link = f"?{urlencode(params)}"
        links[record.source_id] = link
        if citation.title:
            links.setdefault(citation.title, link)
    return links


def citation_source_view_targets(
    source_registry: SourceRegistry,
    citations: list[Citation],
    file_search_store_name: str | None,
) -> list[dict[str, object]]:
    targets: list[dict[str, object]] = []
    seen: set[tuple[str, int | None]] = set()
    for index, citation in enumerate(citations, start=1):
        record = _citation_source_record(
            source_registry,
            citation,
            file_search_store_name,
        )
        if record is None or record.mime_type != "application/pdf":
            continue
        key = (record.source_id, citation.page_number)
        if key in seen:
            continue
        seen.add(key)
        title = citation.title or record.original_filename
        if citation.page_number:
            title = f"{title} - page {citation.page_number}"
        targets.append(
            {
                "citation_index": index,
                "source_id": record.source_id,
                "title": title,
                "page_number": citation.page_number,
            }
        )
    return targets


def _citation_source_record(
    source_registry: SourceRegistry,
    citation: Citation,
    file_search_store_name: str | None,
) -> SourceRecord | None:
    source_id = source_id_from_custom_metadata(citation.custom_metadata)
    record = source_registry.get(source_id) if source_id else None
    if record is None:
        record = source_registry.find_by_filename(citation.title, file_search_store_name)
    return record


def _query_param_value(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) else None


def _positive_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
