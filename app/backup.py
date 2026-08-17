"""SQLite backups: safe online-backup copies to the volume, retention, and a
once-a-day scheduler thread (checks by date so a restart never skips a day)."""
import logging
import os
import re
import sqlite3
import time
from datetime import datetime

from . import config

logger = logging.getLogger("focus.backup")

# focus-YYYYMMDD-HHMMSS.db  (group 1 = the date, used for the daily check)
_NAME_RE = re.compile(r"^focus-(\d{8})-\d{6}\.db$")


def _ensure_dir() -> None:
    os.makedirs(config.BACKUP_DIR, exist_ok=True)


def make_backup() -> str:
    """Write a consistent copy of the live DB using SQLite's online backup API."""
    _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(config.BACKUP_DIR, f"focus-{ts}.db")
    src = sqlite3.connect(config.DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    _prune()
    logger.info("DB backup written: %s", dest)
    return dest


def list_backups() -> list[dict]:
    _ensure_dir()
    out = []
    for name in os.listdir(config.BACKUP_DIR):
        if not _NAME_RE.match(name):
            continue
        st = os.stat(os.path.join(config.BACKUP_DIR, name))
        out.append({
            "name": name,
            "size_kb": round(st.st_size / 1024, 1),
            "when": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    out.sort(key=lambda b: b["name"], reverse=True)
    return out


def _prune() -> None:
    names = sorted((n for n in os.listdir(config.BACKUP_DIR) if _NAME_RE.match(n)),
                   reverse=True)
    for name in names[config.BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(config.BACKUP_DIR, name))
        except OSError:
            pass


def _has_backup_today() -> bool:
    if not os.path.isdir(config.BACKUP_DIR):
        return False
    today = datetime.now().strftime("%Y%m%d")
    return any(
        (m := _NAME_RE.match(n)) and m.group(1) == today
        for n in os.listdir(config.BACKUP_DIR)
    )


def safe_path(name: str) -> str | None:
    """Resolve a backup filename to a path, refusing anything but our pattern."""
    if not _NAME_RE.match(name):
        return None
    path = os.path.join(config.BACKUP_DIR, name)
    return path if os.path.isfile(path) else None


def is_valid_focus_db(path: str) -> tuple[bool, str]:
    """Confirm a file is a healthy SQLite DB with FOCUS's schema before restoring."""
    try:
        con = sqlite3.connect(path)
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                return False, "integrity check failed"
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = {"users", "tasks", "action_items"} - tables
            if missing:
                return False, f"not a FOCUS database (missing tables: {', '.join(sorted(missing))})"
        finally:
            con.close()
        return True, "ok"
    except sqlite3.DatabaseError as exc:
        return False, f"not a valid SQLite file: {exc}"


def restore_from(path: str) -> None:
    """Overwrite the live DB with the contents of `path` (validated by caller).

    Disposes the SQLAlchemy pool first so no connection holds a lock, then copies
    pages in with the online-backup API (keeps the live file's inode/handle)."""
    from .db import engine
    engine.dispose()
    src = sqlite3.connect(path)
    try:
        dst = sqlite3.connect(config.DB_PATH)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    logger.info("DB restored from: %s", path)


def run_daily_loop() -> None:
    """Ensure one backup per calendar day; check hourly so a restart can't skip."""
    while True:
        try:
            if not _has_backup_today():
                make_backup()
        except Exception as exc:  # noqa: BLE001 — a bad backup must not kill the thread
            logger.warning("scheduled backup failed: %s", exc)
        time.sleep(3600)
