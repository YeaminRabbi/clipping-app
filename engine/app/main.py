"""Clipping engine: a local HTTP + WebSocket service the Electron app talks to."""

import asyncio
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, ffmpeg
from .analysis.manager import AnalysisManager
from .api import analysis, captions, clips, exports, projects, sources
from .config import Settings, load_settings
from .db import Database
from .events import EventHub
from .exports import ExportManager
from .ingest import IngestManager
from .media import MediaError

# Paths that must answer before the client has the token (none for now; health is protected too).
PUBLIC_PATHS: set[str] = set()
# <video> and <img> tags can't send headers, so media URLs may carry the token as ?token=.
QUERY_TOKEN_PREFIX = "/media/"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    # Settings may be injected by tests or another launcher instead of load_settings(). Ensure every
    # application-controlled write root exists before database and background services initialize.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_path.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db.migrate()
        app.state.events.attach_loop(asyncio.get_running_loop())
        app.state.ingest.start()
        app.state.exports.start()
        app.state.analysis.start()
        yield
        app.state.ingest.shutdown()
        app.state.exports.shutdown()
        app.state.analysis.shutdown()

    app = FastAPI(title="Clipping Engine", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.db_path)
    app.state.events = EventHub()
    app.state.ingest = IngestManager(settings, app.state.db, app.state.events)
    app.state.exports = ExportManager(settings, app.state.db, app.state.events)
    app.state.analysis = AnalysisManager(settings, app.state.db, app.state.events)

    def token_ok(supplied: str | None) -> bool:
        return settings.token is None or (supplied is not None and secrets.compare_digest(supplied, settings.token))

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        # Any local process or web page can reach a localhost port, so every request must carry the
        # per-launch token that only the Electron app knows.
        if request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
            supplied = request.headers.get("x-engine-token")
            if supplied is None and request.url.path.startswith(QUERY_TOKEN_PREFIX):
                supplied = request.query_params.get("token")
            if not token_ok(supplied):
                return JSONResponse({"detail": "Invalid engine token"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)

    # Added after the token check so it wraps it: rejections still carry CORS headers and the
    # renderer sees a readable 401 instead of a network error.
    # The renderer runs on the Vite dev server in development and on file:// when packaged.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1):\d+|file://.*|null)$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(request: Request):
        info = ffmpeg.detect(settings.bin_dir)
        return {
            "status": "ok",
            "version": __version__,
            "db": {"path": str(settings.db_path), "schema_version": request.app.state.db.schema_version()},
            "ffmpeg": {"ok": info.ok, **asdict(info)},
        }

    @app.websocket("/ws")
    async def events_ws(ws: WebSocket):
        if not token_ok(ws.query_params.get("token")):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        hub: EventHub = ws.app.state.events
        await hub.connect(ws)
        try:
            await ws.send_json({"event": "hello", "data": {"version": __version__}})
            while True:
                # Clients only listen; reading keeps the connection alive and detects disconnects.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub.disconnect(ws)

    @app.exception_handler(MediaError)
    async def media_error(_request: Request, err: MediaError):
        # Media failures inside a request (e.g. face tracking) carry a message meant for the user.
        return JSONResponse({"detail": str(err)}, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    app.include_router(projects.router)
    app.include_router(sources.router)
    app.include_router(clips.router)
    app.include_router(exports.router)
    app.include_router(analysis.router)
    app.include_router(captions.router)
    return app
