# ArchiveVault Indexer

A local tool that runs on the machine where you plug in SAS drives (Windows or Linux Mint). It crawls employee folders and uploads file metadata to your ArchiveVault server — without uploading the actual files, just their index (path, size, dates).

## How It Works

1. You plug in / mount the SAS drive on your machine
2. Run `start.bat` (Windows) or `start.sh` (Linux) — a local web UI opens in your browser
3. Fill in drive number, shelf location, and one or more employee folders
4. Click **Start Indexing** — the tool crawls each folder and uploads metadata to your server
5. Unplug the drive and shelve it — the index is now searchable forever, no need to plug it back in

If the server is unreachable mid-upload, everything is saved to a local `cache/` JSON file first — you can retry later without re-scanning the drive.

## Setup

### 1. Get your server URL and token
From your ArchiveVault admin panel → **Indexer Tokens** → create a new token. Copy it.

### 2. Configure
```bash
cp config.json.example config.json
```
Edit `config.json`:
```json
{
  "server_url": "http://your-server-ip-or-domain",
  "indexer_token": "av_xxxxxxxxxxxxxxxxxxxxxxxx",
  "batch_size": 500,
  "sas_read_speed_mbps": 500,
  "local_ui_port": 8989,
  "cache_dir": "cache"
}
```

### 3. Run

**Windows:**
```
double-click start.bat
```

**Linux:**
```bash
chmod +x start.sh
./start.sh
```

Both will auto-install Python dependencies on first run and open your browser to `http://localhost:8989`.

## Using the Indexer UI

1. **Drive Information** — enter the drive number (e.g. `D042`), capacity, and shelf location (Row / Shelf / Slot)
2. **Employee Folders** — click "+ Add Employee Folder" for each ex-employee whose data is on this drive. Use the **Browse** button to navigate the file system visually, or paste a path directly
3. **Start Indexing** — watch live progress as the tool crawls files and uploads them in batches

## Folder Browsing

The local UI includes a real folder browser (not just a text field) — Python reads your file system on the backend and the browser just displays the results. This works identically on Windows and Linux.

## Cross-Platform Notes

| Behavior | Windows | Linux |
|---|---|---|
| Drive paths | `D:\folder` | `/mnt/sas/folder` |
| File "created" date | Available | Often unavailable on NTFS mounts — stored as `null`, "modified" date is always reliable |
| Folder browsing | Lists drive letters | Lists `/mnt`, `/media`, `/run/media` |

## Retrying a Failed Upload

If indexing completes locally but fails to upload (network issue), check the `cache/` folder for a `.json` file with your drive number. You can re-run the upload manually:

```python
from uploader import ArchiveVaultUploader
import json

with open('config.json') as f:
    config = json.load(f)

uploader = ArchiveVaultUploader(config)
uploader.upload_from_cache('cache/D042_20260630_143000.json')
```

## Requirements
- Python 3.10+
- Network access to your ArchiveVault server (HTTPS recommended in production)

## Files

```
server.py          Local FastAPI server — serves the UI, handles folder browsing
crawler.py         Cross-platform file system crawler
uploader.py         Uploads to server with batching, retries, local cache
ui/index.html       Single-file browser UI
config.json         Your server URL + token (gitignored — never commit this)
cache/              Local fallback JSON files
start.bat / start.sh  Platform-specific launchers
```
