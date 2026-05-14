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
```

You can also leave `.env` unset and enter the key in the Streamlit sidebar. The app never hardcodes or prints the full API key.

## Run

```powershell
streamlit run app.py
```

If `streamlit` is not on PATH, use:

```powershell
py -m streamlit run app.py
```

## Troubleshooting API Key Restrictions

If the app shows `403 PERMISSION_DENIED` with `API_KEY_SERVICE_BLOCKED` for a method such as `RetrieverService.ListFileSearchStores`, the key is valid enough to identify a Google Cloud project, but its API restrictions block Gemini File Search on `generativelanguage.googleapis.com`.

Fix it by creating or selecting a Gemini API key in Google AI Studio, or by editing the key in Google Cloud Console Credentials and changing **API restrictions** so the key is allowed to call the Generative Language API / Gemini API. The Google API key docs state that AI Studio displays keys that have no restrictions or are restricted to the Generative Language API, and the Cloud Console can restrict a key to that API. For local testing an unrestricted key may work, but Google says unrestricted Gemini API traffic keys must be secured by June 19, 2026, so prefer a key restricted to Gemini API only.

## What The App Does

- Loads `GEMINI_API_KEY` from `.env` or accepts a key in the UI.
- Lets the user choose a File Search-supported Gemini model.
- Lists, creates, selects, and deletes Google Gemini File Search stores.
- Creates stores with `models/gemini-embedding-2` so text and PNG/JPEG images can be used for multimodal File Search.
- Uploads files directly into the selected File Search store with `upload_to_file_search_store`.
- Shows long-running upload/import operation output.
- Lists and deletes File Search documents in a selected store.
- Asks questions with only the File Search tool attached to `generate_content`.
- Displays answers, citations, page numbers, media IDs, custom metadata, grounding supports, and raw grounding metadata when returned.
- Can fetch cited media bytes by `media_id` when the API returns media citations.

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
