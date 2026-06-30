"""
crawler.py — Cross-platform file system crawler.
Walks a directory and yields file metadata records.
Works on Windows (NTFS) and Linux (ext4, NTFS via ntfs-3g).
"""
import os
import platform
from pathlib import Path
from datetime import datetime, timezone
from typing import Generator, Dict, Any


def _safe_timestamp(ts: float | None) -> str | None:
    """Convert a filesystem timestamp to ISO format. Returns None on failure."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _get_extension(filename: str) -> str | None:
    """Return lowercase extension without the dot, or None."""
    ext = Path(filename).suffix
    return ext.lstrip(".").lower() if ext else None


def crawl_directory(
    root_path: str,
    emp_code: str,
    base_path: str | None = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Walk root_path recursively and yield one dict per file/directory.

    Args:
        root_path : Absolute path to the employee's folder on the mounted drive.
        emp_code  : Employee code — attached to every record for routing.
        base_path : Optional base to compute depth_level from. Defaults to root_path.
    """
    root = Path(root_path).resolve()
    base = Path(base_path).resolve() if base_path else root

    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {root_path}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=_walk_error):
        current = Path(dirpath).resolve()
        depth = len(current.relative_to(base).parts)

        # Yield directory entry
        try:
            stat = current.stat()
            yield {
                "emp_code": emp_code,
                "file_name": current.name or str(current),
                "file_path": str(current),
                "file_extension": None,
                "file_size_bytes": 0,
                "file_modified_at": _safe_timestamp(stat.st_mtime),
                "file_created_at": _safe_timestamp(_get_ctime(stat)),
                "is_directory": True,
                "depth_level": depth,
            }
        except (PermissionError, OSError):
            pass

        # Yield file entries
        for filename in filenames:
            filepath = current / filename
            try:
                stat = filepath.stat()
                yield {
                    "emp_code": emp_code,
                    "file_name": filename,
                    "file_path": str(filepath),
                    "file_extension": _get_extension(filename),
                    "file_size_bytes": stat.st_size,
                    "file_modified_at": _safe_timestamp(stat.st_mtime),
                    "file_created_at": _safe_timestamp(_get_ctime(stat)),
                    "is_directory": False,
                    "depth_level": depth + 1,
                }
            except (PermissionError, OSError) as e:
                # Yield a placeholder so the error is visible in logs
                yield {
                    "emp_code": emp_code,
                    "file_name": filename,
                    "file_path": str(filepath),
                    "file_extension": _get_extension(filename),
                    "file_size_bytes": 0,
                    "file_modified_at": None,
                    "file_created_at": None,
                    "is_directory": False,
                    "depth_level": depth + 1,
                    "_error": str(e),
                }


def _get_ctime(stat: os.stat_result) -> float | None:
    """
    Return the best available 'created' time.
    - Windows: st_ctime is creation time.
    - Linux:   st_ctime is metadata-change time (not creation); we return None
               so the API stores NULL rather than a misleading value.
    """
    if platform.system() == "Windows":
        return stat.st_ctime
    return None  # Linux NTFS mounts don't reliably expose creation time


def _walk_error(error: OSError) -> None:
    """Non-fatal walk errors are logged to stderr but don't stop the crawl."""
    import sys
    print(f"[WARN] Cannot access: {error.filename} — {error.strerror}", file=sys.stderr)


def count_directory(root_path: str) -> Dict[str, int]:
    """Quick pre-scan: count files and sum sizes without yielding records."""
    total_files = 0
    total_bytes = 0
    root = Path(root_path).resolve()
    for dirpath, dirnames, filenames in os.walk(root, onerror=_walk_error):
        for f in filenames:
            fp = Path(dirpath) / f
            try:
                total_bytes += fp.stat().st_size
                total_files += 1
            except (PermissionError, OSError):
                pass
    return {"total_files": total_files, "total_bytes": total_bytes}
