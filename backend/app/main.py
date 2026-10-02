"""The web app: API plus the built frontend, behind the site's password gate."""

import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .config import get_settings
from .db import init_db, wait_for_database
from .logsafe import install_log_redaction
from .routes import auth, backtests, favourites, market, tools

SECURITY_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}

PROXY_HEADER = "x-gt-proxy"
# The only route open without the proxy secret: the deploy scripts' "is it running?" check.
OPEN_PATHS = {"/api/health"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_database()
    init_db()
    from .db import new_session
    from .market.directory import ensure_fixed_lists

    db = new_session()
    try:
        ensure_fixed_lists(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    install_log_redaction()
    app = FastAPI(title="GandyTrade Lab", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        # "__Host-" makes the browser refuse the cookie unless it's HTTPS-only and for this exact site.
        session_cookie="__Host-gt_session" if settings.cookie_secure else "gt_session",
        max_age=settings.session_hours * 3600,
        same_site="strict",
        https_only=settings.cookie_secure,
    )

    @app.middleware("http")
    async def add_headers(request: Request, call_next):
        # Only Apache (which knows the secret) may talk to the app. Anything else on the
        # server that connects to the port directly has skipped the password gate.
        if settings.proxy_secret and request.url.path not in OPEN_PATHS:
            supplied = request.headers.get(PROXY_HEADER, "")
            if not hmac.compare_digest(supplied.encode(), settings.proxy_secret.encode()):
                return PlainTextResponse("Forbidden.", status_code=403)
        # Simple CSRF guard: state-changing API calls must come from our own page.
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
            if request.headers.get("x-requested-with") != "gandytrade":
                return JSONResponse({"detail": "Request blocked."}, status_code=403)
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth.router)
    app.include_router(market.router)
    app.include_router(favourites.router)
    app.include_router(backtests.router)
    app.include_router(tools.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/robots.txt", include_in_schema=False)
    def robots() -> PlainTextResponse:
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    frontend = Path(settings.frontend_dir)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found."}, status_code=404)
        candidate = (frontend / path).resolve()
        if path and candidate.is_file() and frontend.resolve() in candidate.parents:
            return FileResponse(candidate)
        index = frontend / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return PlainTextResponse("Frontend not built.", status_code=503)

    return app


app = create_app()
