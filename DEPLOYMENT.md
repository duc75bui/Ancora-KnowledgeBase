# Ancora KnowledgeBase App Deployment Guide

This guide is for deploying the local Streamlit app on a Windows server or internal workstation.

The app is a Python Streamlit service that talks to Google Gemini File Search through the official Google GenAI SDK. Google File Search stores remain the retrieval source of truth. The local `.source_files/` folder is only an admin-viewable archive of original uploads.

## 1. Server Requirements

- Windows 10/11 or Windows Server.
- Python 3.11 or newer.
- Outbound HTTPS access to `generativelanguage.googleapis.com`.
- A Gemini API key allowed to call the Generative Language API / Gemini API.
- A local service account or domain account to run the app.
- Optional but recommended: reverse proxy with HTTPS and real authentication.

## 2. Application Folder

Recommended location:

```powershell
C:\Ancora KnowledgeBase App
```

The app expects to run from this folder because local temporary uploads and source archives are relative to the project root.

Important local folders:

- `.source_files\` stores local original-file archives for admin viewing.
- `.tmp_uploads\` stores temporary local upload copies.
- `.venv\` stores the Python virtual environment.

These folders are intentionally not committed to git.

## 3. Install

Open PowerShell as the deployment user:

```powershell
cd "C:\Ancora KnowledgeBase App"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
```

If `py -3.11` is not available, install Python 3.11+ or use:

```powershell
py -m venv .venv
```

## 4. Configure Secrets

Edit `.env`:

```text
GEMINI_API_KEY=your-gemini-api-key
ADMIN_PASSWORD=replace-this-default-password
```

Do not commit `.env`.

The Gemini API key must not be restricted in a way that blocks `generativelanguage.googleapis.com`. If API restrictions are used, allow the Generative Language API / Gemini API.

The current admin password gate is suitable for local/internal testing only. For production, put the app behind SSO, reverse proxy auth, VPN, or another real identity layer.

## 5. Test Before Running

```powershell
cd "C:\Ancora KnowledgeBase App"
.\.venv\Scripts\python.exe -m pytest
```

Expected result should be similar to:

```text
41 passed, 1 skipped
```

The skipped test is the optional live Gemini test unless `RUN_LIVE_GEMINI_TESTS=1` is set.

## 6. Run Manually

For a local-only test:

```powershell
cd "C:\Ancora KnowledgeBase App"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true --browser.gatherUsageStats false
```

For internal network access:

```powershell
cd "C:\Ancora KnowledgeBase App"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Local URL:

```text
http://localhost:8501
```

Internal URL:

```text
http://SERVER_NAME_OR_IP:8501
```

## 7. Windows Firewall

If users need to access the app from another machine:

```powershell
New-NetFirewallRule `
  -DisplayName "Ancora KnowledgeBase App Streamlit 8501" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8501 `
  -Action Allow
```

Prefer limiting the firewall rule to trusted internal subnets.

## 8. Run At Startup With Task Scheduler

Create `run_app.ps1` outside source control or in a secured admin scripts folder:

```powershell
Set-Location "C:\Ancora KnowledgeBase App"
.\.venv\Scripts\python.exe -m streamlit run app.py `
  --server.address 0.0.0.0 `
  --server.port 8501 `
  --server.headless true `
  --browser.gatherUsageStats false
```

Create a scheduled task:

```powershell
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Ancora KnowledgeBase App\run_app.ps1`""

$trigger = New-ScheduledTaskTrigger -AtStartup

Register-ScheduledTask `
  -TaskName "Ancora KnowledgeBase App" `
  -Action $action `
  -Trigger $trigger `
  -Description "Runs the Ancora KnowledgeBase Streamlit app" `
  -RunLevel Highest
```

Alternatively, use a service wrapper such as NSSM if your organization already approves it.

## 9. Reverse Proxy And HTTPS

For anything beyond a local pilot, do not expose raw Streamlit directly to users. Put it behind:

- IIS Application Request Routing, nginx, or another reverse proxy.
- HTTPS/TLS.
- SSO or upstream authentication.
- IP restrictions or VPN.

The built-in `ADMIN_PASSWORD` only controls access to local archived source files in the app. It is not full application authentication.

## 10. Backups

Back up:

- `.env`
- `.source_files\`
- optionally `.tmp_uploads\` if needed for troubleshooting
- the git repository or release package

Google File Search stores are managed by Google and are not backed up by copying this local folder. If source-file viewing matters, `.source_files\` must be backed up.

## 11. Upgrade

Recommended process:

```powershell
cd "C:\Ancora KnowledgeBase App"
git status --short --branch
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest
```

Then restart the scheduled task or service.

## 12. Roll Back To Stable v1.0

Stable checkpoint:

```text
v1.0
```

Before rollback, stop the running app and back up `.env` and `.source_files\`.

To inspect the stable build:

```powershell
git show --stat v1.0
```

To restore the code to `v1.0`:

```powershell
git switch main
git reset --hard v1.0
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest
```

Restart the scheduled task or service after rollback.

## 13. Operational Checks

Health check:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8501
```

Check process:

```powershell
Get-Process | Where-Object { $_.ProcessName -like "python*" }
```

Check port:

```powershell
Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue
```

## 14. Common Issues

`403 PERMISSION_DENIED` with `API_KEY_SERVICE_BLOCKED`:

- The API key exists, but its API restrictions block Gemini File Search.
- Allow the Generative Language API / Gemini API for the key.

Upload succeeds but citations do not show image thumbnails:

- File Search may have used image tokens but omitted `media_id`.
- Admin hover thumbnails can fall back to locally archived image files when the citation title matches a local source image uploaded through this app.

DOCX upload returns MIME type errors:

- Current app versions let the SDK/API infer upload MIME type from the file path.
- Make sure the deployed code includes commit `d41b5d3` or later on `iteration-2`.

Users cannot open original source files:

- They must log in as admin.
- The file must have been uploaded through this app after local source archiving was added.
- `.source_files\` must still contain the archive entry.
