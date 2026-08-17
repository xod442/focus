"""Application factory and entrypoint."""
import threading

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import backup, config
from .db import SessionLocal, init_db
from .deps import get_current_user
from .models import User, STAFF_ROLES
from .routes import account, action_items, admin, auth, dashboard, logs, messages, metrics, tasks

# Paths a user with a pending password change may still reach.
_PW_CHANGE_ALLOWED = {"/account/password", "/logout", "/login"}


def _prefix_location(response):
    """Prepend ROOT_PATH to redirect Location headers so they resolve under the
    edge subpath (routes emit unprefixed paths; this fixes them in one place)."""
    loc = response.headers.get("location")
    if (loc and loc.startswith("/") and config.ROOT_PATH
            and not loc.startswith(config.ROOT_PATH + "/")
            and loc != config.ROOT_PATH):
        response.headers["location"] = config.ROOT_PATH + loc
    return response


async def _enforce_password_change(request, call_next):
    """Redirect users with a pending password change; also root-path-fix redirects."""
    path = request.url.path
    user_id = request.session.get("user_id")
    allowed = path in _PW_CHANGE_ALLOWED or path.startswith("/assets")
    if user_id and not allowed:
        db = SessionLocal()
        try:
            user = db.get(User, user_id)
        finally:
            db.close()
        if user is not None and user.must_change_password:
            return RedirectResponse(f"{config.ROOT_PATH}/account/password", status_code=303)
    return _prefix_location(await call_next(request))


def create_app() -> FastAPI:
    # Disable the built-in docs (they load Swagger assets from a CDN the HPE VPN
    # blocks). We serve an admin-gated, self-hosted Swagger UI below.
    # NOTE: we do NOT set FastAPI root_path. The edge strips the subpath before
    # the app sees it, so routes/mounts match unprefixed paths. ROOT_PATH is used
    # only to build outgoing URLs (templates, redirect Location, invite links).
    app = FastAPI(title="FOCUS", docs_url=None, redoc_url=None, openapi_url=None)

    # Added first = inner; SessionMiddleware added last = outer, so request.session
    # is populated by the time the enforcement middleware runs.
    app.add_middleware(BaseHTTPMiddleware, dispatch=_enforce_password_change)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.SECRET_KEY,
        session_cookie=config.COOKIE_NAME,
        https_only=config.COOKIE_SECURE,
        same_site="lax",
    )

    # Served at /assets, NOT /static — the HPE edge intercepts /static and routes
    # it to a CDN, so assets 404 behind the proxy.
    app.mount(
        "/assets",
        StaticFiles(directory=str(config.BASE_DIR / "app" / "static")),
        name="assets",
    )

    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(admin.router)
    app.include_router(logs.router)
    app.include_router(dashboard.router)
    app.include_router(tasks.router)
    app.include_router(action_items.router)
    app.include_router(messages.router)
    app.include_router(metrics.router)

    # --- Admin-only, self-hosted API docs (Swagger) --------------------------
    _root = config.ROOT_PATH.rstrip("/")

    @app.get("/openapi.json", include_in_schema=False)
    def focus_openapi(user=Depends(get_current_user)):
        if user is None:
            return RedirectResponse("/login", status_code=303)
        if user.role not in STAFF_ROLES:
            return RedirectResponse("/", status_code=303)
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    def focus_docs(user=Depends(get_current_user)):
        if user is None:
            return RedirectResponse("/login", status_code=303)
        if user.role not in STAFF_ROLES:
            return RedirectResponse("/", status_code=303)
        return get_swagger_ui_html(
            openapi_url=f"{_root}/openapi.json",
            title="FOCUS API — Swagger",
            swagger_js_url=f"{_root}/assets/vendor/swagger/swagger-ui-bundle.js",
            swagger_css_url=f"{_root}/assets/vendor/swagger/swagger-ui.css",
        )

    init_db()

    # Daily DB backup scheduler (in-process; single container).
    threading.Thread(target=backup.run_daily_loop, daemon=True).start()

    return app


app = create_app()
