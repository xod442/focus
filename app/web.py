"""Shared Jinja2 templates instance."""
from fastapi.templating import Jinja2Templates

from . import config

templates = Jinja2Templates(directory=str(config.BASE_DIR / "app" / "templates"))

# Root path (subpath behind the HPE edge, e.g. "/holo"); templates prefix all
# internal URLs with {{ rp }} so links/assets resolve under the edge.
templates.env.globals["rp"] = config.ROOT_PATH

# Expose the config module so templates can check live settings (e.g. whether
# the HOLO SSO hand-off is configured) rather than a value snapshotted at
# import time — this also makes it straightforward to test via monkeypatch.
templates.env.globals["config"] = config


def _attention_count(request) -> int:
    """Unread messages + action items flipped to "review" for the signed-in
    user, computed once per request by middleware (see app/main.py) and
    surfaced here as a nav badge on every page."""
    return getattr(request.state, "attention_count", 0)


templates.env.globals["attention_count"] = _attention_count
