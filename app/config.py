"""App configuration, driven by environment variables with dev-friendly defaults."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = os.getenv("FOCUS_DB_PATH", str(BASE_DIR / "focus.db"))

# Session cookie. Per-app name + Secure by default so an edge session-handling
# change (theedge.ext.hpe.com) can't cross-break logins with sibling apps.
SECRET_KEY = os.getenv("FOCUS_SECRET_KEY") or secrets.token_hex(32)
COOKIE_NAME = os.getenv("FOCUS_COOKIE_NAME", "focus_session")
COOKIE_SECURE = os.getenv("FOCUS_COOKIE_SECURE", "1") == "1"

# How long an invite link stays valid.
INVITE_TTL_DAYS = int(os.getenv("FOCUS_INVITE_TTL_DAYS", "7"))

# Subpath the app is served under behind a reverse proxy / the HPE edge
# (e.g. "/focus"), so generated URLs and invite links are correct. Empty = root.
ROOT_PATH = os.getenv("FOCUS_ROOT_PATH", "")

# Default admin, seeded on first startup when there are no users at all.
# Must change password on first login.
DEFAULT_ADMIN_USERNAME = os.getenv("FOCUS_ADMIN_USERNAME", "admin").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.getenv("FOCUS_ADMIN_PASSWORD", "admin")

# Predefined manager (team-lead role: can edit/reassign anyone's tasks & action
# items, plus the full admin console). Seeded independently of the admin — it
# fills in even on a database that already has users but no manager yet — and
# must change password on first login.
DEFAULT_MANAGER_USERNAME = os.getenv("FOCUS_MANAGER_USERNAME", "manager").strip().lower()
DEFAULT_MANAGER_PASSWORD = os.getenv("FOCUS_MANAGER_PASSWORD", "manager")

USING_EPHEMERAL_SECRET = os.getenv("FOCUS_SECRET_KEY") is None

# Backups: written to the volume (default alongside the DB) with retention.
BACKUP_DIR = os.getenv("FOCUS_BACKUP_DIR", str(Path(DB_PATH).parent / "backups"))
BACKUP_KEEP = int(os.getenv("FOCUS_BACKUP_KEEP", "30"))

# How many weeks without an update before an open item is flagged "stale" on
# the executive metrics page.
STALE_WEEKS = int(os.getenv("FOCUS_STALE_WEEKS", "2"))

# ── Single sign-on hand-off to HOLO (same host, separate app/DB) ────────────
# Clicking the "HOLO" button generates a short-lived, signed token (the
# user's own email, nothing else) and redirects to HOLO's SSO-accepting
# route. HOLO independently verifies the signature (shared secret, set
# identically in both apps' env — NOT the same as either app's own
# SECRET_KEY) and logs the person in if a matching HOLO account exists.
# Empty secret = feature disabled (button hidden).
SSO_SHARED_SECRET = os.getenv("SSO_SHARED_SECRET", "").strip()
SSO_SALT = "focus-holo-sso"
SSO_TOKEN_MAX_AGE = 60  # seconds — the link is only valid for a brief window
HOLO_BASE_URL = os.getenv("HOLO_BASE_URL", "http://localhost:9093").rstrip("/")

# ── Read-only JSON API (/api/v1/...) for external integrations, e.g. the ──
# VISTA executive dashboard. Guarded by a static key in the X-API-Key header,
# independent of session-cookie auth. Empty = the API is disabled (404s).
API_KEY = os.getenv("FOCUS_API_KEY", "").strip()
