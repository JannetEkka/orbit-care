"""Orbit: an elder-care and medication platform with the elder at the centre.

`create_app` wires storage, email, the model and the clock together, so tests
can pass in their own. `app` is what uvicorn serves.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import notify
from .api import build_router
from .care import Ctx
from .config import Settings
from .mailer import Mailer, make_mailer
from .store import MemoryStore, Store
from .summary import Summariser

STATIC = Path(__file__).resolve().parent.parent / "static"
PAGES = {"/": "index.html", "/circle": "circle.html", "/bedside": "bedside.html"}
TICK_SECONDS = 300
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
log = logging.getLogger("orbit")


def _make_store(settings: Settings) -> Store:
    if settings.store_backend == "firestore":
        from .store_firestore import FirestoreStore

        return FirestoreStore()
    if settings.store_backend == "postgres":
        from .store_postgres import PostgresStore

        return PostgresStore(settings.database_url)
    return MemoryStore()


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    mailer: Mailer | None = None,
    summariser: Summariser | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    ctx = Ctx(
        settings=settings,
        store=store or _make_store(settings),
        mailer=mailer or make_mailer(settings),
        summariser=summariser or Summariser(settings.gemini_api_key, settings.gemini_model),
        clock=clock or (lambda: datetime.now(UTC)),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(_tick_forever(ctx)) if settings.inprocess_tick else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Orbit", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ctx = ctx

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # A cross-site form cannot set a custom header, so requiring one on every
        # state-changing call blocks cross-site request forgery (with SameSite=Strict).
        changes_state = request.method not in {"GET", "HEAD", "OPTIONS"}
        if changes_state and request.url.path.startswith("/api/") and request.headers.get("x-orbit") != "1":
            response = JSONResponse({"detail": "Missing request header."}, status_code=400)
        else:
            response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException):
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    app.include_router(build_router(ctx))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    for path, filename in PAGES.items():
        app.add_api_route(path, _page(filename), methods=["GET"], include_in_schema=False)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _page(filename: str):
    def serve() -> FileResponse:
        return FileResponse(STATIC / filename, headers={"Cache-Control": "no-cache"})

    return serve


async def _tick_forever(ctx: Ctx) -> None:
    """Local runs only: Cloud Run uses Cloud Scheduler to call /tasks/tick instead."""
    while True:
        try:
            await asyncio.to_thread(notify.run_tick, ctx)
        except Exception:  # noqa: BLE001 - the loop must survive one bad pass
            log.exception("In-process tick failed")
        await asyncio.sleep(TICK_SECONDS)


app = create_app()
