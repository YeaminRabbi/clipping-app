"""Engine entry point. Usage: python run.py --port 8765

Prints `ENGINE_READY port=<port>` on stdout once the server is listening, which the Electron main
process waits for. Pass --port 0 to let the OS pick a free port.
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import socket
import sys
from pathlib import Path

import uvicorn

from app.main import create_app


def setup_logging() -> None:
    """Log to stderr, and to a rotating engine.log when the app gives us a folder (CLIP_LOG_DIR)."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_dir = os.environ.get("CLIP_LOG_DIR")
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(Path(log_dir) / "engine.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
        )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    # uvicorn's own loggers propagate to these handlers too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    # Bind the socket ourselves so --port 0 gives us the real port before announcing readiness.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((args.host, args.port))
    port = sock.getsockname()[1]

    config = uvicorn.Config(create_app(), log_level="info", log_config=None, access_log=False)  # no line per request
    server = uvicorn.Server(config)

    async def serve() -> None:
        task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started:
            if task.done():
                await task
                return
            await asyncio.sleep(0.05)
        print(f"ENGINE_READY port={port}", flush=True)
        await task

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
