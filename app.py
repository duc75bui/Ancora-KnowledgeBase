from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

from src.answer_renderer import render_answer_with_hover
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
    OperationTimeoutError,
    object_to_dict,
    object_display_name,
    object_name,
    operation_status,
)
from src.gemini_client import GeminiClientError, create_client
from src.media_utils import data_url_for_displayable_image, validate_query_image
from src.metadata import (
    MAX_FILE_SEARCH_CUSTOM_METADATA_ITEMS,
    build_common_metadata,
    build_metadata_from_editor_rows,
    build_simple_metadata_filter,
    merge_metadata,
    metadata_filter_value,
    parse_metadata_lines,
)
from src.model_manager import ModelInfo, ModelManager, ModelManagerError, default_model_from
from src.operation_registry import OperationRegistry, PendingOperationRecord
from src.pdf_preview import PDFPreviewError, render_pdf_page_png
from src.pdf_splitter import PDFPart, PDFSplitError, split_pdf_bytes
from src.qa_engine import ANSWER_STYLE_INSTRUCTIONS, DEFAULT_ANSWER_STYLE, QAEngine, QueryImage
from src.source_registry import (
    SourceRecord,
    SourceRegistry,
    metadata_numeric_value,
    metadata_string_value,
    source_id_from_custom_metadata,
)
from src.upload_manager import UploadManager, UploadStageError
from src.validation import accepted_extensions, safe_display_name, validate_file


st.set_page_config(page_title=APP_NAME, page_icon="G", layout="wide")

LAST_ASK_RESULT_KEY = "last_ask_result"


@st.cache_resource(show_spinner=False)
def cached_client(api_key: str):
    return create_client(api_key)


@st.cache_data(show_spinner=False)
def cached_pdf_page_preview(data: bytes, page_number: int | None) -> tuple[int, int, bytes]:
    preview = render_pdf_page_png(data, page_number=page_number)
    return preview.page_number, preview.page_count, preview.png_bytes


@st.cache_resource(show_spinner=False)
def answer_state_cache() -> dict[str, dict[str, Any]]:
    return {}


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
    operation_registry = OperationRegistry()

    stores = load_stores(file_search)
    selected_store_name = render_store_selector(stores, is_admin=is_admin)
    answer_col, source_col = st.columns([0.58, 0.42], gap="large")
    with answer_col:
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
                operation_registry=operation_registry,
                model_manager=model_manager,
                approved_models=approved_models,
                stores=stores,
                selected_store_name=selected_store_name,
                api_key=api_key,
            )
    with source_col:
        render_selected_source_viewer(source_registry, selected_store_name, is_admin)
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
    operation_registry: OperationRegistry,
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
        render_upload_tab(
            file_search,
            upload_manager,
            source_registry,
            operation_registry,
            selected_store_name,
        )
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
    file_search: FileSearchManager,
    upload_manager: UploadManager,
    source_registry: SourceRegistry,
    operation_registry: OperationRegistry,
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
    upload_strategy_label = st.selectbox(
        "Upload method",
        [
            "Files API upload then File Search import (recommended)",
            "Direct upload to File Search store",
        ],
        help=(
            "The two-step method first uploads through Google's standard Files API, then imports "
            "that file into the File Search store. It is more reliable for larger or image-heavy files."
        ),
    )
    upload_strategy = (
        "direct"
        if upload_strategy_label == "Direct upload to File Search store"
        else "files_api_import"
    )
    st.caption(
        "Transient Google upload/import errors such as 500 or 503 are retried up to "
        "3 times before the app reports the failed stage."
    )
    wait_for_import = st.checkbox("Wait for import/indexing operation to finish", value=True)
    poll_interval = st.number_input("Poll interval seconds", min_value=1, max_value=30, value=5)
    operation_timeout_minutes = st.number_input(
        "Import wait timeout minutes",
        min_value=1,
        max_value=120,
        value=30,
        help=(
            "How long this app waits for Google File Search to finish importing. "
            "If it times out, the Google operation may still continue in the background."
        ),
    )
    pdf_split_fallback = st.checkbox(
        "If a PDF import gets repeated Google 500/503 errors, split it into page-range PDFs and retry",
        value=True,
        help=(
            "This is an admin fallback for PDFs that Google rejects during File Search ingestion. "
            "The app imports smaller PDF page ranges into the same File Search store and keeps "
            "the original PDF as the local citation source."
        ),
    )
    pdf_pages_per_part = st.number_input(
        "PDF fallback pages per part",
        min_value=5,
        max_value=75,
        value=25,
        disabled=not pdf_split_fallback,
    )
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
                        timeout_seconds=float(operation_timeout_minutes) * 60,
                        upload_strategy=upload_strategy,
                    )
                    st.success(f"Uploaded {uploaded_file.name} as {result.mime_type}")
                    st.caption(
                        f"Upload method: {result.upload_strategy}; operation kind: "
                        f"{result.operation_kind}; Google file: {result.file_name or 'not returned'}"
                    )
                    st.caption(f"Local source archive id: {source_record.source_id}")
                    st.json(to_plain_data(result.final_operation or result.operation))
                    if not wait_for_import:
                        save_pending_operation(
                            operation_registry,
                            result=result,
                            filename=uploaded_file.name,
                            selected_store_name=selected_store_name,
                            source_record=source_record,
                            status_label="Started import/indexing operation.",
                        )
                except OperationTimeoutError as exc:
                    elapsed_seconds = exc.elapsed_seconds or 0
                    timeout_seconds = exc.timeout_seconds or float(operation_timeout_minutes) * 60
                    st.warning(
                        f"{uploaded_file.name}: Google File Search is still importing this file. "
                        "The app stopped waiting before the operation completed, but the operation "
                        "may continue in Google in the background."
                    )
                    st.caption(
                        "Import wait diagnostics: "
                        f"configured timeout {timeout_seconds / 60:.1f} minute(s), "
                        f"elapsed wait {elapsed_seconds / 60:.1f} minute(s), "
                        f"poll interval {float(poll_interval):.1f} second(s)."
                    )
                    st.caption(f"Local source archive id kept: {source_record.source_id}")
                    timeout_payload = {
                        "operation": to_plain_data(exc.operation),
                        "status": to_plain_data(exc.status),
                    }
                    st.json(timeout_payload)
                    save_pending_operation(
                        operation_registry,
                        operation=exc.operation,
                        operation_kind=(
                            "upload_to_file_search_store"
                            if upload_strategy == "direct"
                            else "import_file"
                        ),
                        upload_strategy=upload_strategy,
                        filename=uploaded_file.name,
                        selected_store_name=selected_store_name,
                        source_record=source_record,
                        status=to_plain_data(exc.status),
                        status_label="Saved pending import operation for later refresh.",
                    )
                    st.info(
                        "The remaining selected files were not uploaded in this batch. "
                        "Use Documents > List documents later to check whether the pending import finished, "
                        "or rerun Upload with a longer import wait timeout."
                    )
                    break
                except UploadStageError as exc:
                    fallback_started = False
                    if (
                        source_record
                        and exc.retryable
                        and pdf_split_fallback
                        and validation.mime_type == "application/pdf"
                    ):
                        fallback_started = upload_pdf_split_fallback(
                            upload_manager=upload_manager,
                            operation_registry=operation_registry,
                            source_record=source_record,
                            filename=uploaded_file.name,
                            data=data,
                            selected_store_name=selected_store_name,
                            wait_for_import=wait_for_import,
                            poll_interval=float(poll_interval),
                            timeout_seconds=float(operation_timeout_minutes) * 60,
                            pages_per_part=int(pdf_pages_per_part),
                        )
                    if source_record and not fallback_started:
                        source_registry.delete_source(source_record.source_id)
                    if fallback_started:
                        st.caption(
                            f"Original full-PDF import failed before Google returned an operation: {exc}"
                        )
                    else:
                        st.error(f"{uploaded_file.name}: {exc}")
                    if exc.retryable:
                        if fallback_started:
                            st.info(
                                "The original upload attempt cannot be refreshed because Google did not "
                                "return an operation name. The split fallback part imports are the active "
                                "File Search documents for this PDF."
                            )
                        else:
                            st.info(
                                "Google returned a transient server-side error before the app received "
                                "a usable File Search operation. No pending operation can be refreshed "
                                "for the original upload attempt. Wait a few minutes, then retry this file; "
                                "if it keeps failing, use the PDF split fallback or split/export the document."
                            )
                        break
                except (ValueError, GeminiAPIError) as exc:
                    if source_record:
                        source_registry.delete_source(source_record.source_id)
                    st.error(f"{uploaded_file.name}: {exc}")

    render_pending_operations(file_search, operation_registry, selected_store_name)


def upload_pdf_split_fallback(
    upload_manager: UploadManager,
    operation_registry: OperationRegistry,
    source_record: SourceRecord,
    filename: str,
    data: bytes,
    selected_store_name: str,
    wait_for_import: bool,
    poll_interval: float,
    timeout_seconds: float,
    pages_per_part: int,
) -> bool:
    st.warning(
        "The original PDF failed during Google File Search ingestion. Trying the PDF split "
        "fallback with smaller page-range PDFs."
    )
    try:
        split_result = split_pdf_bytes(
            data=data,
            original_filename=filename,
            output_root=upload_manager.upload_dir,
            pages_per_part=pages_per_part,
        )
    except (ValueError, PDFSplitError) as exc:
        st.error(f"PDF split fallback could not start: {exc}")
        return False

    st.caption(
        f"Split {filename} into {len(split_result.parts)} part(s) from "
        f"{split_result.original_page_count} original page(s)."
    )
    part_upload_strategy = "files_api_import"
    started_count = 0
    completed_count = 0
    pending_count = 0

    for part in split_result.parts:
        part_metadata = pdf_part_file_search_metadata(source_record, part)
        try:
            with st.spinner(
                f"Importing {part.filename} ({part.part_index}/{part.part_count})"
            ):
                result = upload_manager.upload_file_path(
                    file_search_store_name=selected_store_name,
                    file_path=part.file_path,
                    mime_type="application/pdf",
                    display_name=part.filename,
                    custom_metadata=part_metadata,
                    wait=wait_for_import,
                    poll_interval=poll_interval,
                    timeout_seconds=timeout_seconds,
                    upload_strategy=part_upload_strategy,
                )
            started_count += 1
            if result.final_operation is not None:
                completed_count += 1
            else:
                pending_count += 1
                save_pending_operation(
                    operation_registry,
                    result=result,
                    filename=part.filename,
                    selected_store_name=selected_store_name,
                    source_record=source_record,
                    status_label=f"Saved pending import operation for {part.filename}.",
                )
            st.success(
                f"Imported PDF part {part.part_index}/{part.part_count}: "
                f"pages {part.page_start}-{part.page_end}."
            )
        except OperationTimeoutError as exc:
            started_count += 1
            pending_count += 1
            save_pending_operation(
                operation_registry,
                operation=exc.operation,
                operation_kind=(
                    "upload_to_file_search_store"
                    if part_upload_strategy == "direct"
                    else "import_file"
                ),
                upload_strategy=part_upload_strategy,
                filename=part.filename,
                selected_store_name=selected_store_name,
                source_record=source_record,
                status=to_plain_data(exc.status),
                status_label=f"Saved pending import operation for {part.filename}.",
            )
            st.warning(
                f"PDF split fallback started part {part.part_index}/{part.part_count}, "
                "but Google was still importing it when the app stopped waiting. "
                "The remaining parts were not uploaded."
            )
            break
        except (ValueError, GeminiAPIError) as exc:
            st.error(
                f"PDF split fallback failed on part {part.part_index}/{part.part_count} "
                f"({part.filename}): {exc}"
            )
            break

    if started_count:
        st.info(
            f"PDF split fallback started {started_count} part import(s): "
            f"{completed_count} completed while waiting, {pending_count} pending/not waited. "
            "Citations from these parts map back to the original archived PDF when Google "
            "returns the app metadata."
        )
        st.caption(f"Original local source archive id kept: {source_record.source_id}")
        return True
    return False


def pdf_part_file_search_metadata(source_record: SourceRecord, part: PDFPart) -> list[dict[str, Any]]:
    essential = [
        {"key": "source_id", "string_value": source_record.source_id},
        {"key": "source_filename", "string_value": source_record.original_filename},
        {"key": "source_sha256", "string_value": source_record.sha256},
        {"key": "source_upload_mode", "string_value": "pdf_split_fallback"},
        {"key": "source_part_filename", "string_value": part.filename},
        {"key": "source_page_start", "numeric_value": part.page_start},
        {"key": "source_page_end", "numeric_value": part.page_end},
        {"key": "source_part_index", "numeric_value": part.part_index},
        {"key": "source_part_count", "numeric_value": part.part_count},
    ]
    metadata = list(essential)
    seen = {str(item["key"]) for item in metadata}
    for item in source_record.custom_metadata or []:
        key = str(item.get("key", "") or "")
        if not key or key in seen:
            continue
        metadata.append(item)
        seen.add(key)
        if len(metadata) >= MAX_FILE_SEARCH_CUSTOM_METADATA_ITEMS:
            break
    return metadata


def save_pending_operation(
    operation_registry: OperationRegistry,
    filename: str,
    selected_store_name: str,
    source_record: SourceRecord,
    result: Any | None = None,
    operation: Any | None = None,
    operation_kind: str | None = None,
    upload_strategy: str | None = None,
    status: dict[str, Any] | None = None,
    status_label: str | None = None,
) -> None:
    operation = operation or getattr(result, "operation", None)
    status_obj = operation_status(operation)
    operation_name = status_obj.name
    if not operation_name:
        st.warning("Could not save pending operation because Google did not return an operation name.")
        return
    stored_status = status or to_plain_data(status_obj)
    operation_registry.upsert(
        operation_name=operation_name,
        operation_kind=operation_kind or getattr(result, "operation_kind", "import_file"),
        file_search_store_name=selected_store_name,
        filename=filename,
        source_id=source_record.source_id,
        upload_strategy=upload_strategy or getattr(result, "upload_strategy", "files_api_import"),
        file_name=getattr(result, "file_name", None),
        status=stored_status,
        done=bool(status_obj.done),
    )
    if status_label:
        st.caption(status_label)


def render_pending_operations(
    file_search: FileSearchManager,
    operation_registry: OperationRegistry,
    selected_store_name: str,
) -> None:
    st.divider()
    st.subheader("Pending import operations")
    records = operation_registry.list_records(selected_store_name)
    if not records:
        st.caption("No saved pending import operations for this store.")
        return

    st.dataframe(
        [
            {
                "filename": record.filename,
                "operation": record.operation_name,
                "kind": record.operation_kind,
                "method": record.upload_strategy,
                "done": record.done,
                "updated_at": record.updated_at,
                "source_id": record.source_id,
            }
            for record in records
        ],
        width="stretch",
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Refresh pending import statuses"):
            for record in records:
                refresh_pending_operation(file_search, operation_registry, record)
    with col2:
        if st.button("Clear completed import records"):
            removed = operation_registry.clear_completed()
            st.success(f"Cleared {removed} completed import record(s).")
            st.rerun()

    for record in records[:20]:
        with st.expander(f"{record.filename} - {record.operation_name}"):
            st.json(record.status or {})
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Refresh this operation", key=f"refresh-{record.operation_name}"):
                    refresh_pending_operation(file_search, operation_registry, record)
            with col2:
                if st.button("Forget this operation record", key=f"forget-{record.operation_name}"):
                    operation_registry.delete(record.operation_name)
                    st.rerun()


def refresh_pending_operation(
    file_search: FileSearchManager,
    operation_registry: OperationRegistry,
    record: PendingOperationRecord,
) -> None:
    try:
        operation = file_search.get_operation(record.operation_name, record.operation_kind)
    except GeminiAPIError as exc:
        st.error(f"{record.filename}: could not refresh operation status. {exc}")
        return

    status = operation_status(operation)
    operation_registry.upsert(
        operation_name=record.operation_name,
        operation_kind=record.operation_kind,
        file_search_store_name=record.file_search_store_name,
        filename=record.filename,
        source_id=record.source_id,
        upload_strategy=record.upload_strategy,
        file_name=record.file_name,
        status=to_plain_data(status),
        done=status.done,
    )
    if status.error:
        st.error(f"{record.filename}: import operation finished with an API error.")
        st.json(to_plain_data(status.error))
    elif status.done:
        st.success(f"{record.filename}: import operation is complete.")
    else:
        st.info(f"{record.filename}: import operation is still running.")


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
    restore_answer_state_from_query_params()

    with st.form("ask-form"):
        question = st.text_area("Question", height=120, key="ask_question")
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
        answer_state = run_ask_query(
            qa_engine=qa_engine,
            file_search=file_search,
            source_registry=source_registry,
            question=question,
            model=model,
            selected_store_name=selected_store_name,
            use_web=use_web,
            answer_style=answer_style,
            query_image_files=query_image_files or [],
            filter_key=filter_key,
            filter_operator=filter_operator,
            filter_value=filter_value,
            filter_value_type=filter_value_type,
            advanced_metadata_filter=advanced_metadata_filter,
            top_k=int(top_k) if top_k else None,
            reverify_answer=reverify_answer,
            include_media_previews=include_media_previews,
            is_admin=is_admin,
        )
        if answer_state is not None:
            remember_answer_state(answer_state)

    answer_state = st.session_state.get(LAST_ASK_RESULT_KEY)
    if answer_state:
        render_answer_state(
            file_search=file_search,
            source_registry=source_registry,
            answer_state=answer_state,
            is_admin=is_admin,
        )


def run_ask_query(
    qa_engine: QAEngine,
    file_search: FileSearchManager,
    source_registry: SourceRegistry,
    question: str,
    model: str,
    selected_store_name: str | None,
    use_web: bool,
    answer_style: str,
    query_image_files: list[Any],
    filter_key: str,
    filter_operator: str,
    filter_value: str,
    filter_value_type: str,
    advanced_metadata_filter: str,
    top_k: int | None,
    reverify_answer: bool,
    include_media_previews: bool,
    is_admin: bool,
) -> dict[str, Any] | None:
    answer_id = uuid.uuid4().hex
    query_images = build_query_images(query_image_files)
    if query_images is None:
        return None

    if not use_web and not selected_store_name:
        st.error("Select or create a File Search store, or enable web answers for a generic web question.")
        return None
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
            return None
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
                    top_k=top_k,
                    query_images=query_images,
                    answer_style=answer_style,
                )
        except (ValueError, GeminiAPIError) as exc:
            st.error(str(exc))
            return None

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
                    top_k=top_k,
                    query_images=query_images,
                    answer_style=answer_style,
                )
                result = type(result)(
                    text=result.text,
                    grounding=supplement_missing_citation_details(
                        result.grounding,
                        initial_result.grounding,
                        allow_index_fallback=True,
                    ),
                    raw_response=result.raw_response,
                )
            except (ValueError, GeminiAPIError) as exc:
                st.warning(f"Review pass failed; showing the initial answer. {exc}")
                result = initial_result

    source_citations = combined_source_citations(
        result.grounding.citations,
        initial_result.grounding.citations if initial_result else [],
    )
    source_view_links = citation_source_view_links(
        source_registry,
        source_citations,
        file_search_store_name=selected_store_name,
        answer_id=answer_id,
    )
    image_preview_notes = image_preview_notes_for_citations(
        result.grounding.citations,
        is_admin=is_admin,
    )
    media_data_urls = {}
    source_image_data_urls = {}
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

    return {
        "question": question,
        "answer_id": answer_id,
        "result": result,
        "initial_result": initial_result,
        "metadata_filter": metadata_filter,
        "use_web": use_web,
        "query_image_count": len(query_images),
        "source_citations": source_citations,
        "source_view_links": source_view_links,
        "image_preview_notes": image_preview_notes,
        "media_data_urls": media_data_urls,
        "source_image_data_urls": source_image_data_urls,
        "selected_store_name": selected_store_name,
    }


def render_answer_state(
    file_search: FileSearchManager,
    source_registry: SourceRegistry,
    answer_state: dict[str, Any],
    is_admin: bool,
) -> None:
    result = answer_state["result"]
    initial_result = answer_state.get("initial_result")
    metadata_filter = answer_state.get("metadata_filter")
    source_citations = answer_state.get("source_citations", result.grounding.citations)
    source_view_links = answer_state.get("source_view_links", {})
    image_preview_notes = answer_state.get("image_preview_notes", {})
    media_data_urls = answer_state.get("media_data_urls", {})
    source_image_data_urls = answer_state.get("source_image_data_urls", {})

    st.markdown("### Answer")
    question = (answer_state.get("question") or "").strip()
    if question:
        st.caption(f"Question: {question}")
    st.caption(
        "Source mode: Google Search grounding"
        if answer_state.get("use_web")
        else "Source mode: selected File Search store"
    )
    answer_store_name = answer_state.get("selected_store_name")
    if answer_store_name:
        st.caption(f"Answer store: `{answer_store_name}`")
    if metadata_filter:
        st.caption(f"Metadata filter: `{metadata_filter}`")
    if initial_result:
        st.caption("Review pass: second File Search reanalysis was enabled.")
    query_image_count = answer_state.get("query_image_count") or 0
    if query_image_count:
        st.caption(f"Used {query_image_count} uploaded image(s) as question context.")

    if result.text:
        rendered = render_answer_with_hover(
            result.text,
            result.grounding,
            media_data_urls=media_data_urls,
            source_image_data_urls=source_image_data_urls,
            image_preview_notes=image_preview_notes,
            source_view_links=source_view_links,
        )
        st.markdown(rendered.html, unsafe_allow_html=True)
    else:
        st.markdown("_No text returned._")
    render_citation_pdf_open_buttons(
        source_registry,
        source_citations,
        file_search_store_name=answer_store_name,
        answer_id=answer_state.get("answer_id"),
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


def remember_answer_state(answer_state: dict[str, Any]) -> None:
    st.session_state[LAST_ASK_RESULT_KEY] = answer_state
    answer_id = answer_state.get("answer_id")
    if not isinstance(answer_id, str) or not answer_id:
        return
    cache = answer_state_cache()
    cache[answer_id] = answer_state
    while len(cache) > 20:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)


def restore_answer_state_from_query_params() -> None:
    answer_id = _query_param_value(st.query_params.get("answer_id"))
    if not answer_id:
        return
    current = st.session_state.get(LAST_ASK_RESULT_KEY)
    if isinstance(current, dict) and current.get("answer_id") == answer_id:
        return
    cached = answer_state_cache().get(answer_id)
    if cached:
        st.session_state[LAST_ASK_RESULT_KEY] = cached


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
    answer_id: str | None = None,
) -> None:
    targets = citation_source_view_targets(
        source_registry,
        citations,
        file_search_store_name,
    )
    if targets:
        st.markdown("#### Source PDF")
        for target in targets:
            page_number = target.get("page_number")
            title = target.get("title") or "PDF source"
            label = f"Show citation {target['citation_index']} PDF"
            if page_number:
                label = f"{label} at page {page_number}"
            if st.button(label, key=f"open-source-{target['citation_index']}-{target['source_id']}"):
                st.query_params["source_id"] = str(target["source_id"])
                if answer_id:
                    st.query_params["answer_id"] = answer_id
                if page_number:
                    st.query_params["page"] = str(page_number)
                elif "page" in st.query_params:
                    del st.query_params["page"]
                st.rerun()
            st.caption(title)
        missing_pages = [target for target in targets if not target.get("page_number")]
        if missing_pages:
            st.caption("Some cited PDFs can be opened, but Google did not return page numbers for them.")
        return

    if citations:
        with st.expander("Why no cited PDF button is shown"):
            for line in citation_pdf_link_diagnostics(source_registry, citations, file_search_store_name):
                st.write(f"- {line}")


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
    st.subheader("Cited source")
    source_id = _query_param_value(st.query_params.get("source_id"))
    if not source_id:
        st.info("Cited source previews will appear here.")
        st.caption("Hover over highlighted answer text or use a Source PDF button to show the cited page.")
        return

    page_number = _positive_int(_query_param_value(st.query_params.get("page")))
    if st.button("Clear source preview"):
        clear_source_query_params()
        st.rerun()

    record = source_registry.get(source_id)
    if record is None:
        st.warning("The cited source file is not available in the local archive.")
        return
    if selected_store_name and record.file_search_store_name != selected_store_name:
        st.warning("This local source belongs to a different File Search store.")
        return
    if not is_admin and record.mime_type != "application/pdf":
        st.info("Admin login is required to view this locally archived source file.")
        return
    if not is_admin:
        st.caption(
            "Showing a cited PDF preview only. Admin login is required to browse the "
            "source archive or download original files."
        )

    render_source_record_viewer(
        source_registry=source_registry,
        record=record,
        key_prefix=f"linked-source-{record.source_id}",
        page_number=page_number,
        force_pdf_preview=True,
        allow_download=is_admin,
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
        page_number=citation_original_page_number(citation),
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
    allow_download: bool = True,
) -> None:
    st.caption(f"Original source: {record.original_filename}")
    try:
        data = source_registry.file_bytes(record)
    except OSError as exc:
        st.error(f"Could not read archived source file: {exc}")
        return

    if allow_download:
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
    try:
        rendered_page, page_count, png_bytes = cached_pdf_page_preview(data, page_number)
    except PDFPreviewError as exc:
        st.error(str(exc))
        return

    st.caption(f"Previewing page {rendered_page} of {page_count}.")
    st.image(
        png_bytes,
        caption=f"PDF page {rendered_page}",
        width="stretch",
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
    answer_id: str | None = None,
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
        page_number = citation_original_page_number(citation)
        params = {"source_id": record.source_id}
        if page_number:
            params["page"] = str(page_number)
        if answer_id:
            params["answer_id"] = answer_id
        link = f"?{urlencode(params)}"
        links[citation_source_link_key("source_id", record.source_id, citation.page_number)] = link
        links[citation_source_link_key("source_id", record.source_id, page_number)] = link
        links.setdefault(record.source_id, link)
        if citation.title:
            links[citation_source_link_key("title", citation.title, citation.page_number)] = link
            links[citation_source_link_key("title", citation.title, page_number)] = link
            links.setdefault(citation.title, link)
    return links


def citation_source_link_key(kind: str, value: str, page_number: int | None) -> str:
    page = "" if page_number is None else str(page_number)
    return f"{kind}:{value}:{page}"


def combined_source_citations(
    primary: list[Citation],
    fallback: list[Citation],
) -> list[Citation]:
    combined: list[Citation] = []
    seen: set[tuple[str, str, int | None]] = set()
    for citation in [*primary, *fallback]:
        key = _citation_identity(citation)
        if key in seen:
            continue
        seen.add(key)
        combined.append(citation)
    return combined


def citation_original_page_number(citation: Citation) -> int | None:
    if citation.page_number is None:
        return None
    page_start = metadata_numeric_value(citation.custom_metadata, "source_page_start")
    page_end = metadata_numeric_value(citation.custom_metadata, "source_page_end")
    if page_start is None:
        return citation.page_number

    original_page = int(page_start) + citation.page_number - 1
    if page_end is not None:
        original_page = min(original_page, int(page_end))
    return max(1, original_page)


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
        page_number = citation_original_page_number(citation)
        key = (record.source_id, page_number)
        if key in seen:
            continue
        seen.add(key)
        title = citation.title or record.original_filename
        if page_number:
            title = f"{title} - page {page_number}"
        targets.append(
            {
                "citation_index": index,
                "source_id": record.source_id,
                "title": title,
                "page_number": page_number,
            }
        )
    return targets


def citation_pdf_link_diagnostics(
    source_registry: SourceRegistry,
    citations: list[Citation],
    file_search_store_name: str | None,
) -> list[str]:
    pdf_records = [
        record
        for record in source_registry.list_records(file_search_store_name)
        if record.mime_type == "application/pdf"
    ]
    if not pdf_records:
        return [
            "No PDFs are available in this app's local source archive for the selected store.",
            "PDF links only work for files uploaded through this app after local source archiving was added.",
            "On Streamlit Cloud, local `.source_files/` content is not the same as your local machine and may be empty after redeploys.",
        ]

    lines = [
        f"Found {len(pdf_records)} archived PDF(s) for the selected store, but none matched the returned citation metadata.",
    ]
    for index, citation in enumerate(citations[:5], start=1):
        source_id = source_id_from_custom_metadata(citation.custom_metadata)
        metadata_filename = metadata_string_value(citation.custom_metadata, "source_filename")
        page = citation.page_number if citation.page_number is not None else "not returned"
        title = citation.title or citation.uri or citation.media_id or "untitled citation"
        lines.append(
            f"Citation {index}: title={title!r}, source_id={source_id or 'not returned'}, "
            f"source_filename={metadata_filename or 'not returned'}, page={page}."
        )
    lines.append(
        "To create reliable PDF links, upload the PDF through this app's Admin Upload tab so File Search receives source_id metadata and the app archives the original PDF."
    )
    return lines


def _citation_identity(citation: Citation) -> tuple[str, str, int | None]:
    source_id = source_id_from_custom_metadata(citation.custom_metadata)
    if source_id:
        return ("source_id", source_id, citation.page_number)
    if citation.media_id:
        return ("media_id", citation.media_id, citation.page_number)
    if citation.uri:
        return ("uri", citation.uri, citation.page_number)
    if citation.title:
        return ("title", citation.title, citation.page_number)
    return ("text", citation.text or "", citation.page_number)


def _citation_source_record(
    source_registry: SourceRegistry,
    citation: Citation,
    file_search_store_name: str | None,
) -> SourceRecord | None:
    source_id = source_id_from_custom_metadata(citation.custom_metadata)
    record = source_registry.get(source_id) if source_id else None
    if record is None:
        metadata_filename = metadata_string_value(citation.custom_metadata, "source_filename")
        for reference in (
            metadata_filename,
            citation.title,
            citation.uri,
        ):
            record = source_registry.find_by_reference(reference, file_search_store_name)
            if record is not None:
                break
    return record


def _query_param_value(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) else None


def clear_source_query_params() -> None:
    for key in ("source_id", "page"):
        if key in st.query_params:
            del st.query_params[key]


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
