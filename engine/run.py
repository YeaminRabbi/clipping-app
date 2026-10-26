"""Engine entry point. Usage: python run.py --port 8765

Prints `ENGINE_READY port=<port>` on stdout once the server is listening, which the Electron main
process waits for. Pass --port 0 to let the OS pick a free port.
"""

import argparse
import asyncio
import socket
import sys

import uvicorn

from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    # Bind the socket ourselves so --port 0 gives us the real port before announcing readiness.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((args.host, args.port))
    port = sock.getsockname()[1]

    config = uvicorn.Config(create_app(), log_level="info")
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
