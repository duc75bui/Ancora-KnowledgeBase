# Gemini File Search RAG Streamlit App

This is a basic local Streamlit app for Retrieval Augmented Generation with the Google Gemini File Search API. It uses Google File Search stores as the source of truth: Google imports files, chunks them, creates embeddings, indexes content, retrieves relevant chunks, returns grounding metadata, and manages File Search documents.

The app does not implement a custom RAG pipeline. It does not use SQLite, local vector databases, LangChain, LlamaIndex, FAISS, Chroma, Pinecone, Google Search grounding, URL Context, or browser search.

## Sources Used

- Google Gemini File Search guide: https://ai.google.dev/gemini-api/docs/file-search
- File Search stores API reference: https://ai.google.dev/api/file-search/file-search-stores
- File Search documents API reference: https://ai.google.dev/api/file-search/documents
- Google Gen AI Python SDK docs: https://googleapis.github.io/python-genai/

## Setup

Requires Python 3.11 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

For exact stable build `v1.0` dependencies, install from the lock file:

```powershell
py -m pip install -r requirements.lock.txt
```

Edit `.env` and set:

```text
GEMINI_API_KEY=your-gemini-api-key
ADMIN_PASSWORD=admin123
```

You can also leave `.env` unset and enter the key in the Streamlit sidebar. The app never hardcodes or prints the full API key.

`ADMIN_PASSWORD` controls access to locally archived original files. The default `admin123` is only for local testing.

## Run

```powershell
streamlit run app.py
```

If `streamlit` is not on PATH, use:

```powershell
py -m streamlit run app.py
```

For server or internal-network deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Troubleshooting API Key Restrictions

If the app shows `403 PERMISSION_DENIED` with `API_KEY_SERVICE_BLOCKED` for a method such as `RetrieverService.ListFileSearchStores`, the key is valid enough to identify a Google Cloud project, but its API restrictions block Gemini File Search on `generativelanguage.googleapis.com`.

Fix it by creating or selecting a Gemini API key in Google AI Studio, or by editing the key in Google Cloud Console Credentials and changing **API restrictions** so the key is allowed to call the Generative Language API / Gemini API. The Google API key docs state that AI Studio displays keys that have no restrictions or are restricted to the Generative Language API, and the Cloud Console can restrict a key to that API. For local testing an unrestricted key may work, but Google says unrestricted Gemini API traffic keys must be secured by June 19, 2026, so prefer a key restricted to Gemini API only.

## What The App Does

- Loads `GEMINI_API_KEY` from `.env` or accepts a key in the UI.
- Lets the user choose a File Search-supported Gemini model.
- Normal users only see the Ask workflow.
- Admin users can list, create, select, and delete Google Gemini File Search stores.
- Creates stores with `models/gemini-embedding-2` so text and PNG/JPEG images can be used for multimodal File Search.
- Admin users can upload files directly into the selected File Search store with `upload_to_file_search_store`.
- Lets the SDK/API infer upload MIME type from the file path, matching Google's direct-upload example. The app still validates MIME locally for user feedback and source archive metadata.
- Archives a local copy of newly uploaded original files under `.source_files/` for admin-only viewing.
- Attaches `source_id`, `source_filename`, and `source_sha256` as File Search custom metadata during upload.
- Admin users can view long-running upload/import operation output.
- Admin users can list and delete File Search documents in a selected store.
- Asks questions with only the File Search tool attached to `generate_content`.
- Lets the user attach optional query-context images in the Ask tab using Gemini inline image input. Supported image input formats are PNG, JPEG, WebP, HEIC, and HEIF.
- Displays answers, citations, page numbers, media IDs, custom metadata, grounding supports, and raw grounding metadata when returned.
- Highlights answer spans when Google returns `groundingSupports`; hover or focus the highlighted text to inspect the retrieved snippet, source title, page number, and optional image preview.
- Can fetch cited media bytes by `media_id` when the API returns media citations.
- Can automatically fetch image media returned by File Search `media_id` and embed browser-displayable thumbnails in citation hover cards.
- For logged-in admins, can also show a locally archived source-image thumbnail in hover cards when a citation maps back to an image uploaded through this app.
- Lets logged-in admins download or preview locally archived source PDFs/images/text files from citation details and the Documents tab.

## Admin Source File Viewing

Google File Search stores are still the retrieval source of truth. The local `.source_files/` archive exists only so an admin can view or download the original uploaded file later. It is not used for chunking, embedding, indexing, retrieval, or answering.

Only files uploaded through this app after this feature was added have local `source_id` metadata. Existing File Search documents may still cite text and page numbers, but the app cannot link them to a local original unless they were archived locally during upload.

For local testing, the default admin password is:

```text
admin123
```

Set `ADMIN_PASSWORD` in `.env` before using real documents. This Streamlit password gate is not production authentication. For deployment, replace it with OAuth, reverse proxy auth, or another real identity layer.

## Supported Models

The dropdown follows the File Search guide's supported model table:

- `gemini-3.1-pro-preview`
- `gemini-3.1-flash-lite`
- `gemini-3.1-flash-lite-preview`
- `gemini-3-flash-preview`
- `gemini-2.5-pro`
- `gemini-2.5-flash-lite`

## Supported File Types

The official File Search guide lists many supported application and text MIME types. This first app validates common document, code, spreadsheet, archive, and image formats locally, including:

- PDF, TXT, Markdown, CSV, TSV, HTML, XML, JSON, RTF, YAML
- DOC, DOCX, XLSX, PPTX
- SQL, Python, JavaScript, TypeScript, CSS, shell scripts, PowerShell, Java, Go, Ruby, Rust, C/C++, C#, Swift, PHP, LaTeX
- ZIP
- PNG and JPEG images

Google still enforces the final server-side MIME support. Audio and video formats are not supported by File Search according to the guide. PNG and JPEG images must be at most 4K x 4K pixels.

## File Search Data Model

According to the official guide, raw `File` objects uploaded through the File API are temporary and deleted after 48 hours. The imported data in a File Search store persists until manually deleted or until the model is deprecated. This app treats File Search stores and documents as the durable source of truth.

## Limits And Current Limitations

- Maximum file size per document is 100 MB.
- File Search is not supported in the Live API.
- File Search cannot currently be combined with tools such as Google Search grounding or URL Context.
- Store size limits depend on account tier; Google recommends keeping each store under 20 GB for retrieval latency.
- This app uses Google-managed default chunking. It does not expose custom chunk sizes yet.
- The local MIME allowlist covers common official types rather than every MIME type listed in the guide.
- Metadata filters are exposed as an advanced text box, but the app does not yet provide a visual metadata builder.
- The model detail page for `gemini-2.5-flash` says File Search is supported, but the File Search guide's supported model table does not include it, so this app keeps the initial dropdown aligned to the File Search guide table.
- Original-file viewing is only available for local files uploaded through this app after source archiving was added.
- PDF previews are embedded as browser data URLs; large PDFs may be better downloaded than previewed inline.
- Citation hover depends on Google returning `groundingSupports` span metadata. If no span metadata is returned, the app still shows the citation list and raw grounding metadata.
- Google File Search currently documents multimodal image support for PNG and JPEG. The hover renderer can display common browser-safe raster formats if Google returns those bytes or if an admin views a locally archived image, but File Search ingestion is still limited by Google's supported formats.
- Image hover previews depend on Google returning `media_id` values in grounding metadata, or on the citation metadata mapping to a local archived source image for an admin. If a PDF contains an embedded image but Google does not return a `media_id`, the app cannot know which embedded image to display in the hover card.
- Ask-tab image attachments are prompt context, not File Search documents. They are sent inline to Gemini and are limited to about 18 MB combined in this app to stay below Google's 20 MB inline request guidance.

## Tests

Run the unit and mocked API tests:

```powershell
py -m pytest
```

The live smoke test is skipped unless both `RUN_LIVE_GEMINI_TESTS=1` and `GEMINI_API_KEY` are set:

```powershell
$env:RUN_LIVE_GEMINI_TESTS="1"
py -m pytest -m live
```

The live test lists File Search stores and does not fake success when credentials are missing.
