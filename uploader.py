"""
uploader.py — Uploads indexed file records to ArchiveVault server.
Features:
  - Batched uploads (configurable batch size)
  - Local cache fallback (saves to JSON if server unreachable)
  - Retry on failure
  - Progress callback support
"""
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, List, Dict, Any

import httpx


class ArchiveVaultUploader:
    def __init__(self, config: dict):
        self.server_url = config["server_url"].rstrip("/")
        self.token = config["indexer_token"]
        self.batch_size = config.get("batch_size", 500)
        self.cache_dir = Path(config.get("cache_dir", "cache"))
        self.cache_dir.mkdir(exist_ok=True)
        self.headers = {
            "X-Indexer-Token": self.token,
            "Content-Type": "application/json"
        }
        self.timeout = httpx.Timeout(60.0)

    def verify_token(self) -> bool:
        """Check connectivity and token validity."""
        try:
            resp = httpx.get(
                f"{self.server_url}/api/v1/indexer/token/verify",
                headers=self.headers,
                timeout=10
            )
            return resp.status_code == 200
        except Exception:
            return False

    def start_session(self, payload: dict) -> dict:
        """Start an indexer session on the server. Returns session info."""
        resp = httpx.post(
            f"{self.server_url}/api/v1/indexer/session/start",
            headers=self.headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def upload_batch(self, session_key: str, files: List[Dict[str, Any]]) -> bool:
        """Upload one batch of file records. Returns True on success."""
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{self.server_url}/api/v1/indexer/session/{session_key}/files",
                    headers=self.headers,
                    json={"files": files},
                    timeout=self.timeout
                )
                resp.raise_for_status()
                return True
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise e
        return False

    def complete_session(self, session_key: str, total_files: int,
                         total_size_bytes: int, error_log: str | None = None) -> dict:
        """Mark session as complete."""
        resp = httpx.post(
            f"{self.server_url}/api/v1/indexer/session/{session_key}/complete",
            headers=self.headers,
            json={
                "total_files": total_files,
                "total_size_bytes": total_size_bytes,
                "error_log": error_log
            },
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def save_to_cache(self, drive_number: str, payload: dict, records: list) -> Path:
        """Save everything to a local JSON cache file for later retry."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        cache_file = self.cache_dir / f"{drive_number}_{ts}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "saved_at": ts,
                "session_payload": payload,
                "records": records
            }, f, ensure_ascii=False, default=str)
        return cache_file

    def upload_from_cache(self, cache_file: Path,
                          progress_cb: Callable | None = None) -> bool:
        """Retry a previously cached indexing job."""
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        session = self.start_session(data["session_payload"])
        session_key = session["session_key"]
        records = data["records"]

        total_files = 0
        total_bytes = 0
        errors = []

        for i in range(0, len(records), self.batch_size):
            batch = records[i: i + self.batch_size]
            try:
                self.upload_batch(session_key, batch)
                for r in batch:
                    if not r.get("is_directory"):
                        total_files += 1
                        total_bytes += r.get("file_size_bytes", 0)
                if progress_cb:
                    progress_cb(min(i + self.batch_size, len(records)), len(records))
            except Exception as e:
                errors.append(str(e))

        self.complete_session(
            session_key, total_files, total_bytes,
            "\n".join(errors) if errors else None
        )
        cache_file.rename(cache_file.with_suffix(".uploaded.json"))
        return True

    def run_full_index(
        self,
        session_payload: dict,
        file_generator,
        drive_number: str,
        progress_cb: Callable | None = None
    ) -> dict:
        """
        Full indexing run:
          1. Collect all records from generator (also saves local cache)
          2. Start server session
          3. Upload in batches
          4. Complete session
        Returns summary dict.
        """
        # Always collect to cache first
        all_records = []
        errors = []
        total_files = 0
        total_bytes = 0

        for record in file_generator:
            if "_error" in record:
                errors.append(f"{record['file_path']}: {record['_error']}")
                record.pop("_error")
            if not record["is_directory"]:
                total_files += 1
                total_bytes += record.get("file_size_bytes", 0)
            all_records.append(record)

        cache_path = self.save_to_cache(drive_number, session_payload, all_records)

        # Start session
        session = self.start_session(session_payload)
        session_key = session["session_key"]

        # Upload in batches
        uploaded = 0
        for i in range(0, len(all_records), self.batch_size):
            batch = all_records[i: i + self.batch_size]
            self.upload_batch(session_key, batch)
            uploaded += len(batch)
            if progress_cb:
                progress_cb(uploaded, len(all_records))

        # Complete
        result = self.complete_session(
            session_key, total_files, total_bytes,
            "\n".join(errors) if errors else None
        )

        # Mark cache as uploaded
        cache_path.rename(cache_path.with_suffix(".uploaded.json"))

        return {
            "session_key": session_key,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "errors": errors,
            "cache_file": str(cache_path)
        }
