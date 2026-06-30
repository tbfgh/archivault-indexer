"""
server.py — Local indexer UI server.
Runs on localhost:8989, opens browser automatically.
Handles folder browsing (OS-level) and drives indexing.
"""
import json
import os
import sys
import platform
import threading
import webbrowser
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from crawler import crawl_directory, count_directory
from uploader import ArchiveVaultUploader

# ── Load config ───────────────────────────────────────────────
CONFIG_FILE = Path(__file__).parent / "config.json"
if not CONFIG_FILE.exists():
    print("ERROR: config.json not found.")
    print("Copy config.json.example to config.json and fill in your server URL and token.")
    sys.exit(1)

with open(CONFIG_FILE, "r") as f:
    CONFIG = json.load(f)

uploader = ArchiveVaultUploader(CONFIG)
UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(title="ArchiveVault Indexer", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

# ── State ─────────────────────────────────────────────────────
indexing_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "status": "idle",
    "message": "",
    "errors": []
}


# ── Models ────────────────────────────────────────────────────
class EmployeeEntry(BaseModel):
    emp_code: str
    full_name: str
    department: Optional[str] = None
    folder_path: str


class IndexRequest(BaseModel):
    drive_number: str
    capacity_gb: float
    shelf_row: str
    shelf_shelf: str
    shelf_slot: str
    employees: List[EmployeeEntry]


# ── Routes ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_ui():
    index_file = UI_DIR / "index.html"
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/api/config")
def get_config():
    return {
        "server_url": CONFIG.get("server_url"),
        "token_set": bool(CONFIG.get("indexer_token")),
        "batch_size": CONFIG.get("batch_size", 500)
    }


@app.get("/api/verify")
def verify_connection():
    ok = uploader.verify_token()
    return {"connected": ok, "server_url": CONFIG.get("server_url")}


@app.get("/api/browse")
def browse_filesystem(path: Optional[str] = None):
    """Return directory listing for folder browser."""
    system = platform.system()

    if path is None or path == "":
        # Return roots
        if system == "Windows":
            import string
            drives = []
            for letter in string.ascii_uppercase:
                p = Path(f"{letter}:\\")
                if p.exists():
                    drives.append({"name": f"{letter}:\\", "path": str(p), "type": "drive"})
            return {"current": "", "parent": None, "entries": drives}
        else:
            # Linux — start from /mnt or /media
            roots = []
            for base in ["/mnt", "/media", "/run/media"]:
                bp = Path(base)
                if bp.exists():
                    try:
                        for entry in sorted(bp.iterdir()):
                            if entry.is_dir():
                                roots.append({
                                    "name": entry.name,
                                    "path": str(entry),
                                    "type": "directory"
                                })
                    except PermissionError:
                        pass
            if not roots:
                roots.append({"name": "/", "path": "/", "type": "directory"})
            return {"current": "", "parent": None, "entries": roots}

    target = Path(path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    entries = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.is_dir():
                try:
                    size_info = {"file_count": sum(1 for _ in entry.rglob("*") if _.is_file())}
                except Exception:
                    size_info = {"file_count": "?"}
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "directory",
                    **size_info
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    parent = str(target.parent) if str(target.parent) != str(target) else None
    return {"current": str(target), "parent": parent, "entries": entries}


@app.get("/api/preview")
def preview_folder(path: str):
    """Quick file count and size estimate before indexing."""
    try:
        result = count_directory(path)
        size_gb = result["total_bytes"] / (1024 ** 3)
        speed = CONFIG.get("sas_read_speed_mbps", 500)
        est_seconds = (result["total_bytes"] / (1024 * 1024)) / speed
        return {
            "path": path,
            "total_files": result["total_files"],
            "total_bytes": result["total_bytes"],
            "total_gb": round(size_gb, 3),
            "estimated_index_seconds": round(est_seconds, 1)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/index")
def start_indexing(payload: IndexRequest):
    global indexing_state

    if indexing_state["running"]:
        raise HTTPException(status_code=409, detail="Indexing already in progress")

    # Validate paths exist
    for emp in payload.employees:
        if not Path(emp.folder_path).exists():
            raise HTTPException(
                status_code=400,
                detail=f"Folder not found for {emp.emp_code}: {emp.folder_path}"
            )

    indexing_state = {
        "running": True, "progress": 0, "total": 0,
        "status": "starting", "message": "Preparing indexing session...", "errors": []
    }

    def run():
        global indexing_state
        try:
            session_payload = {
                "drive_number": payload.drive_number,
                "capacity_gb": payload.capacity_gb,
                "shelf_row": payload.shelf_row,
                "shelf_shelf": payload.shelf_shelf,
                "shelf_slot": payload.shelf_slot,
                "employees": [
                    {
                        "emp_code": e.emp_code,
                        "full_name": e.full_name,
                        "department": e.department,
                        "folder_path": e.folder_path
                    }
                    for e in payload.employees
                ]
            }

            # Count total files first for progress
            indexing_state["message"] = "Scanning file counts..."
            total_files = 0
            for emp in payload.employees:
                c = count_directory(emp.folder_path)
                total_files += c["total_files"]
            indexing_state["total"] = total_files

            # Build combined generator
            def combined_generator():
                for emp in payload.employees:
                    indexing_state["message"] = f"Indexing: {emp.full_name} ({emp.emp_code})"
                    yield from crawl_directory(emp.folder_path, emp.emp_code)

            def progress_cb(done, total):
                indexing_state["progress"] = done
                indexing_state["total"] = max(total, 1)

            indexing_state["status"] = "indexing"
            result = uploader.run_full_index(
                session_payload,
                combined_generator(),
                payload.drive_number,
                progress_cb=progress_cb
            )

            indexing_state.update({
                "running": False,
                "status": "completed",
                "progress": result["total_files"],
                "total": result["total_files"],
                "message": f"Done! {result['total_files']:,} files indexed.",
                "errors": result.get("errors", [])
            })

        except Exception as e:
            indexing_state.update({
                "running": False,
                "status": "error",
                "message": f"Error: {str(e)}",
                "errors": [str(e)]
            })

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return {"message": "Indexing started", "status": "running"}


@app.get("/api/status")
def get_status():
    return indexing_state


@app.get("/api/cache")
def list_cache():
    cache_dir = Path(CONFIG.get("cache_dir", "cache"))
    files = []
    if cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            files.append({
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": f.stat().st_mtime
            })
    return {"cache_files": files}


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    port = CONFIG.get("local_ui_port", 8989)
    url = f"http://localhost:{port}"
    print(f"\n  ArchiveVault Indexer")
    print(f"  ─────────────────────────────")
    print(f"  Open browser: {url}")
    print(f"  Server: {CONFIG.get('server_url')}")
    print(f"  Press Ctrl+C to stop\n")

    # Open browser after short delay
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
