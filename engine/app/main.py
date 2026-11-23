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
from .analysis.transcribe import speech_device
from .api import analysis, captions, clips, exports, projects, sources, ui
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
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

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
    app.state.analysis = AnalysisManager(settings, app.state.db, app.state.events, app.state.exports)

    def token_ok(supplied: str | None) -> bool:
        if not settings.token or supplied is None:
            return False
        # Compared as bytes: compare_digest refuses non-ASCII strings.
        return secrets.compare_digest(supplied.encode(), settings.token.encode())

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        # A page that points its own domain name at this machine is refused by the name it asks for.
        if request.url.hostname not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Unknown host"}, status_code=status.HTTP_421_MISDIRECTED_REQUEST)
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
    # The renderer runs on the Vite dev server in development and on file:// when packaged. Not "null",
    # which any website can send from a sandboxed frame.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1):\d+|file://.*)$",
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
            "speech": asdict(speech_device()),
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
    app.include_router(ui.router)
    return app
