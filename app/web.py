"""Shared Jinja2 templates instance."""
from fastapi.templating import Jinja2Templates

from . import config

templates = Jinja2Templates(directory=str(config.BASE_DIR / "app" / "templates"))

# Root path (subpath behind the HPE edge, e.g. "/holo"); templates prefix all
# internal URLs with {{ rp }} so links/assets resolve under the edge.
templates.env.globals["rp"] = config.ROOT_PATH
